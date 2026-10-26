using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Text;

const string defaultServiceUrl =
    "https://usstage262.dayforcehcm.com/OData/configwizard11stage/Reports";

var serviceUrl = Environment.GetEnvironmentVariable("ODATA_SERVICE_URL")
    ?? defaultServiceUrl;
var username = Environment.GetEnvironmentVariable("ODATA_USERNAME");
var password = Environment.GetEnvironmentVariable("ODATA_PASSWORD");

if (string.IsNullOrWhiteSpace(username) || string.IsNullOrWhiteSpace(password))
{
    Console.Error.WriteLine(
        "Set ODATA_USERNAME and ODATA_PASSWORD environment variables before running.");
    return 1;
}

if (!Uri.TryCreate(serviceUrl, UriKind.Absolute, out var currentUri)
    || (currentUri.Scheme != Uri.UriSchemeHttps
        && currentUri.Scheme != Uri.UriSchemeHttp))
{
    Console.Error.WriteLine("ODATA_SERVICE_URL must be an absolute HTTP or HTTPS URL.");
    return 1;
}

var logName = $"odata-http-{DateTimeOffset.Now:yyyyMMdd-HHmmss-fff}.http";
var logPath = Path.Combine(Environment.CurrentDirectory, logName);
Console.WriteLine($"Raw HTTP transcript: {logPath}");

var sendCredentials = false;
var redirectCount = 0;

while (true)
{
    var requestText = BuildRequest(currentUri, sendCredentials, username, password);
    var requestLogText = sendCredentials
        ? requestText.Replace(
            GetAuthorizationHeader(username, password),
            "Authorization: <redacted>\r\n",
            StringComparison.Ordinal)
        : requestText;

    Console.WriteLine();
    Console.WriteLine("========== REQUEST ==========");
    Console.Write(requestLogText);
    await File.AppendAllTextAsync(logPath, requestLogText, Encoding.ASCII);

    var rawResponse = await SendRawRequestAsync(currentUri, requestText);
    var parsedResponse = ParseResponse(rawResponse);

    Console.WriteLine();
    Console.WriteLine("========== RAW RESPONSE ==========");
    await Console.OpenStandardOutput().WriteAsync(rawResponse);
    Console.WriteLine();

    await using (var logFile = new FileStream(
        logPath,
        FileMode.Append,
        FileAccess.Write,
        FileShare.Read))
    {
        var separator = Encoding.ASCII.GetBytes(
            "\r\n========== RAW RESPONSE ==========\r\n");
        await logFile.WriteAsync(separator);
        await logFile.WriteAsync(rawResponse);
        await logFile.WriteAsync(Encoding.ASCII.GetBytes(
            "\r\n========== END RESPONSE ==========\r\n\r\n"));
    }

    if (parsedResponse.StatusCode == 401
        && !sendCredentials
        && parsedResponse.Headers.TryGetValue("WWW-Authenticate", out var challenge)
        && challenge.Split(',', StringSplitOptions.TrimEntries)
            .Any(part => part.StartsWith("Basic", StringComparison.OrdinalIgnoreCase)))
    {
        sendCredentials = true;
        Console.WriteLine(
            "Basic challenge received; resending with Authorization: Basic.");
        continue;
    }

    if (IsRedirect(parsedResponse.StatusCode)
        && parsedResponse.Headers.TryGetValue("Location", out var location))
    {
        var nextUri = new Uri(currentUri, location);
        if (!SameOrigin(currentUri, nextUri))
        {
            Console.WriteLine($"Blocked cross-origin redirect to {nextUri}");
            return 1;
        }

        redirectCount++;
        if (redirectCount > 10)
        {
            Console.WriteLine("Stopped after 10 redirects.");
            return 1;
        }

        currentUri = nextUri;
        Console.WriteLine($"Following redirect to {currentUri}");
        continue;
    }

    Console.WriteLine($"HTTP status: {parsedResponse.StatusCode}");
    return parsedResponse.StatusCode is >= 200 and < 300 ? 0 : 1;
}

static string BuildRequest(Uri uri, bool includeCredentials, string username, string password)
{
    var target = string.IsNullOrEmpty(uri.PathAndQuery) ? "/" : uri.PathAndQuery;
    var request = new StringBuilder()
        .Append("GET ").Append(target).AppendLine(" HTTP/1.1")
        .Append("Host: ").AppendLine(uri.Authority)
        .AppendLine("Accept: application/json")
        .AppendLine("Accept-Encoding: identity")
        .AppendLine("Connection: close");

    if (includeCredentials)
    {
        request.Append(GetAuthorizationHeader(username, password));
    }

    request.AppendLine();
    return request.ToString();
}

static string GetAuthorizationHeader(string username, string password)
{
    var encodedCredentials = Convert.ToBase64String(
        Encoding.UTF8.GetBytes($"{username}:{password}"));
    return $"Authorization: Basic {encodedCredentials}\r\n";
}

static async Task<byte[]> SendRawRequestAsync(Uri uri, string requestText)
{
    using var tcpClient = new TcpClient();
    await tcpClient.ConnectAsync(uri.Host, uri.Port);

    Stream stream = tcpClient.GetStream();
    if (uri.Scheme == Uri.UriSchemeHttps)
    {
        var tlsStream = new SslStream(stream, leaveInnerStreamOpen: false);
        await tlsStream.AuthenticateAsClientAsync(uri.Host);
        stream = tlsStream;
    }

    await using (stream)
    {
        var requestBytes = Encoding.ASCII.GetBytes(requestText);
        await stream.WriteAsync(requestBytes);
        await stream.FlushAsync();

        using var response = new MemoryStream();
        var buffer = new byte[8192];
        int bytesRead;
        while ((bytesRead = await stream.ReadAsync(buffer)) > 0)
        {
            response.Write(buffer, 0, bytesRead);
        }

        return response.ToArray();
    }
}

static (int StatusCode, Dictionary<string, string> Headers) ParseResponse(
    byte[] responseBytes)
{
    var headerEnd = FindHeaderEnd(responseBytes);
    if (headerEnd < 0)
    {
        throw new InvalidDataException(
            "The response did not contain an HTTP header terminator.");
    }

    var headerText = Encoding.Latin1.GetString(responseBytes, 0, headerEnd);
    var lines = headerText.Split("\r\n", StringSplitOptions.None);
    var statusParts = lines[0].Split(' ', 3, StringSplitOptions.RemoveEmptyEntries);
    if (statusParts.Length < 2
        || !int.TryParse(statusParts[1], out var statusCode))
    {
        throw new InvalidDataException($"Invalid HTTP status line: {lines[0]}");
    }

    var headers = new Dictionary<string, string>(
        StringComparer.OrdinalIgnoreCase);
    foreach (var line in lines.Skip(1))
    {
        var separator = line.IndexOf(':');
        if (separator <= 0)
        {
            continue;
        }

        var name = line[..separator].Trim();
        var value = line[(separator + 1)..].Trim();
        headers[name] = headers.TryGetValue(name, out var previous)
            ? $"{previous}, {value}"
            : value;
    }

    return (statusCode, headers);
}

static int FindHeaderEnd(byte[] bytes)
{
    for (var index = 0; index <= bytes.Length - 4; index++)
    {
        if (bytes[index] == '\r'
            && bytes[index + 1] == '\n'
            && bytes[index + 2] == '\r'
            && bytes[index + 3] == '\n')
        {
            return index;
        }
    }

    return -1;
}

static bool IsRedirect(int statusCode)
{
    return statusCode is 301 or 302 or 303 or 307 or 308;
}

static bool SameOrigin(Uri first, Uri second)
{
    return first.Scheme.Equals(second.Scheme, StringComparison.OrdinalIgnoreCase)
        && first.Host.Equals(second.Host, StringComparison.OrdinalIgnoreCase)
        && first.Port == second.Port;
}
