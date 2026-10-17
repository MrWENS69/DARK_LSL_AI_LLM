"""HTTP out (llHTTPRequest, answered by the test or by sim.http_handler) and HTTP in (llRequestURL, llHTTPResponse, sim.http_in_request). Mixed into Simulator."""

from .errors import ScriptError
from .limits import (HTTP_BODY_DEFAULT, HTTP_BODY_MAXLENGTH, HTTP_BODY_TRUNCATED, HTTP_CUSTOM_HEADER,
                     HTTP_METHOD, MAX_URLS, URL_REQUEST_DENIED, URL_REQUEST_GRANTED)
from .signatures import CONSTANTS
from .values import to_string, type_of, NULL_KEY
from .world import HttpOutRequest, clip_text


def http_options(params):
    """The HTTP_* flags of llHTTPRequest as {flag: value}, plus the (name, value) custom headers."""
    options, headers, i = {}, [], 0
    while i < len(params):
        if params[i] == HTTP_CUSTOM_HEADER:
            headers.append(tuple(to_string(v) for v in params[i + 1:i + 3]))
            i += 3
        else:
            if i + 1 < len(params):
                options[params[i]] = params[i + 1]
            i += 2
    return options, headers


CONTENT_TYPES = {CONSTANTS[name]: mime for name, mime in (
    ("CONTENT_TYPE_TEXT", "text/plain"), ("CONTENT_TYPE_HTML", "text/html"), ("CONTENT_TYPE_XML", "application/xml"),
    ("CONTENT_TYPE_XHTML", "application/xhtml+xml"), ("CONTENT_TYPE_ATOM", "application/atom+xml"),
    ("CONTENT_TYPE_JSON", "application/json"), ("CONTENT_TYPE_LLSD", "application/llsd+xml"),
    ("CONTENT_TYPE_FORM", "application/x-www-form-urlencoded"), ("CONTENT_TYPE_RSS", "application/rss+xml"))
    if name in CONSTANTS}


class HttpMixin(object):

    def _drop_urls(self, obj):
        """Rez and region restart invalidate every HTTP-in URL of the object, as on the grid."""
        for script in obj.scripts:
            for url in list(script.urls):
                self.ll_ReleaseURL(script, url)

    def _answer(self, request, status, body, metadata=None):
        """Deliver the response: the body is cut at the request's HTTP_BODY_MAXLENGTH and the
        metadata then starts with [HTTP_BODY_TRUNCATED, limit]."""
        metadata = list(metadata or [])
        if len(body.encode("utf-8")) > request.maxlen:
            body = clip_text(body, request.maxlen)
            metadata = [HTTP_BODY_TRUNCATED, request.maxlen] + metadata
        request.response = (status, body)
        self._http_pending.remove(request)
        self._post_prim(request.script, "http_response", [request.key, status, metadata, body])

    def http_respond(self, status=200, body="", request=None, metadata=None):
        """Answer a pending llHTTPRequest (the oldest unanswered one by default), then run."""
        if request is None:
            if not self._http_pending:
                raise AssertionError("no pending HTTP request")
            request = self._http_pending[0]
        self._answer(request, status, body, metadata)
        self.run()

    def auto_respond(self):
        """Called by run(): hand every unanswered request to http_handler. Returns how many it answered."""
        count = 0
        for request in list(self._http_pending):
            answer = self.http_handler(request)
            if answer is None:
                continue
            status, body = answer
            self._answer(request, status, body)
            count += 1
        return count

    def http_in_request(self, url, method="GET", body="", headers=None):
        """Send a request to a script's HTTP-in URL; returns (status, body, content_type)."""
        base = url.split("?", 1)[0]
        script = None
        for known, owner in self.http_in.items():
            if base == known or base.startswith(known + "/"):
                script = owner
                break
        if script is None:
            return (404, "no such URL", "text/plain")
        key = self.new_key()
        path_info = base[len(known):]
        query = url.split("?", 1)[1] if "?" in url else ""
        request_headers = {k.lower(): v for k, v in (headers or {}).items()}
        request_headers.setdefault("x-script-url", known)
        request_headers.setdefault("x-path-info", path_info)
        request_headers.setdefault("x-query-string", query)
        request_headers.setdefault("x-remote-ip", "127.0.0.1")
        request_headers.setdefault("user-agent", "lsltest")
        self.http_in_pending[key] = {"status": None, "body": "", "content_type": "text/plain", "headers": request_headers}
        script.post("http_request", [key, method, clip_text(body, 2048)])
        self.run()
        answer = self.http_in_pending.pop(key)
        if answer["status"] is None:
            return (500, "the script did not answer", "text/plain")
        return (answer["status"], answer["body"], answer["content_type"])

    def ll_HTTPRequest(self, script, url, params, body):
        options, headers = http_options(params)
        if any(h and h[0].lower() == "content-type" for h in headers):
            raise ScriptError("Script run-time error",
                              "llHTTPRequest: Content-Type is set with HTTP_MIMETYPE, not with HTTP_CUSTOM_HEADER")
        # the grid throttles an object to 25 requests per 20 seconds and returns NULL_KEY beyond that
        recent = 0
        for r in reversed(self.http_out):
            if self.time - r.time >= 20.0:
                break
            if r.script.obj is script.obj:
                recent += 1
        if recent >= 25:
            return NULL_KEY
        method = to_string(options.get(HTTP_METHOD, "GET"))
        maxlen = options.get(HTTP_BODY_MAXLENGTH, HTTP_BODY_DEFAULT)
        if type_of(maxlen) != "integer" or maxlen <= 0:
            maxlen = HTTP_BODY_DEFAULT
        key = self.new_key()
        request = HttpOutRequest(key, script, url, method, body, list(params), self.time, maxlen)
        self._keep(self.http_out, request)
        self._http_pending.append(request)
        return key

    def ll_RequestURL(self, script):
        key = self.new_key()
        if len(script.urls) >= MAX_URLS:
            script.post("http_request", [key, URL_REQUEST_DENIED, ""])
            return key
        url = "http://sim.invalid/cap/%s" % self.new_key()
        self.http_in[url] = script
        script.urls.add(url)
        script.post("http_request", [key, URL_REQUEST_GRANTED, url])
        return key

    ll_RequestSecureURL = ll_RequestURL

    def ll_ReleaseURL(self, script, url):
        self.http_in.pop(url, None)
        script.urls.discard(url)

    def ll_GetFreeURLs(self, script):
        return MAX_URLS - len(script.urls)

    def ll_HTTPResponse(self, script, request_id, status, body):
        pending = self.http_in_pending.get(request_id)
        if pending is not None:
            pending["status"] = status
            pending["body"] = body

    def ll_SetContentType(self, script, request_id, content_type):
        pending = self.http_in_pending.get(request_id)
        if pending is not None:
            pending["content_type"] = CONTENT_TYPES.get(content_type, "text/plain")

    def ll_GetHTTPHeader(self, script, request_id, header):
        pending = self.http_in_pending.get(request_id)
        if pending is None:
            return ""
        return pending["headers"].get(header, "")      # the name must be lower case or it matches nothing (wiki)
