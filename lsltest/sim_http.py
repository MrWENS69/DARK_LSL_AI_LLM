"""HTTP out (llHTTPRequest) and HTTP in (llRequestURL, llHTTPResponse). Mixed into Simulator."""

from .errors import ScriptError
from .limits import (HTTP_BODY_DEFAULT, HTTP_BODY_MAXLENGTH, HTTP_METHOD, MAX_URLS, URL_REQUEST_DENIED,
                     URL_REQUEST_GRANTED, _CONTENT_TYPES)
from .values import to_string, type_of, NULL_KEY
from .world import HttpOutRequest, _http_options


class HttpMixin(object):
    """HTTP out (llHTTPRequest) and HTTP in (llRequestURL, llHTTPResponse)."""

    # --- HTTP out -------------------------------------------------------------

    def ll_HTTPRequest(self, script, url, params, body):
        options, headers = _http_options(params)
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

    # --- HTTP in --------------------------------------------------------------

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
            pending["content_type"] = _CONTENT_TYPES.get(content_type, "text/plain")

    def ll_GetHTTPHeader(self, script, request_id, header):
        pending = self.http_in_pending.get(request_id)
        if pending is None:
            return ""
        return pending["headers"].get(header, "")      # the name must be lower case or it matches nothing (wiki)
