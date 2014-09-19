# -*- coding: utf-8 -*-

import static, time
from email.utils import formatdate, parsedate
from os import path
from django.conf import settings
from django.core.handlers.wsgi import WSGIHandler
from django.contrib.staticfiles.handlers import StaticFilesHandler as DebugHandler

try:
    from urllib.parse import urlparse
except ImportError:     # Python 2
    from urlparse import urlparse
from django.contrib.staticfiles import utils

try:
    from django.core.handlers.wsgi import get_path_info
except ImportError:  # django < 1.7
    try:
        from django.core.handlers.base import get_path_info
    except ImportError:     # django < 1.5
        import sys
        py3 = sys.version_info[0] == 3

        def get_path_info(environ):
            """
            Returns the HTTP request's PATH_INFO as a unicode string.
            """
            path_info = environ.get('PATH_INFO', str('/'))
            # Under Python 3, strings in environ are decoded with ISO-8859-1;
            # re-encode to recover the original bytestring provided by the web server.
            if py3:
                path_info = path_info.encode('iso-8859-1')
            # It'd be better to implement URI-to-IRI decoding, see #19508.
            return path_info.decode('utf-8')

class GzipCling(static.Cling):
    def __call__(self, environ, start_response):
        """Respond to a request when called in the usual WSGI way."""
        if environ['REQUEST_METHOD'] not in ('GET', 'HEAD'):
            return self.method_not_allowed(environ, start_response)
        path_info = environ.get('PATH_INFO', '')
        full_path = self._full_path(path_info)
        """If not under root then return file not found"""
        if not self._is_under_root(full_path):
            return self.not_found(environ, start_response)
        """ if file is a directory then return moved permanently or a directory index file"""
        if path.isdir(full_path):
            if full_path[-1] != '/' or full_path == self.root:
                location = util.request_uri(environ, include_query=False) + '/'
                if environ.get('QUERY_STRING'):
                    location += '?' + environ.get('QUERY_STRING')
                headers = [('Location', location)]
                return self.moved_permanently(environ, start_response, headers)
            else:
                full_path = self._full_path(path_info + self.index_file)

        #Innocent unless proved guilty
        if_gzip = False
        #if accept encoding contain gzip
        if 'gzip' in environ['HTTP_ACCEPT_ENCODING']:
            # check if gzip version exists
            if path.exists(full_path + '.gz'):
                if_gzip = True
                full_path = full_path + '.gz'
        content_type = self._guess_type(full_path)
        try:
            etag, last_modified = self._conditions(full_path, environ)
            headers = [('Date', formatdate(time.time())),
                       ('Last-Modified', last_modified),
                       ('ETag', etag)]
            if_modified = environ.get('HTTP_IF_MODIFIED_SINCE')
            if if_modified and (parsedate(if_modified)
                                >= parsedate(last_modified)):
                return self.not_modified(environ, start_response, headers)
            if_none = environ.get('HTTP_IF_NONE_MATCH')
            if if_none and (if_none == '*' or etag in if_none):
                return self.not_modified(environ, start_response, headers)
            file_like = self._file_like(full_path)
            headers.append(('Content-Type', content_type))
            if if_gzip:
                headers.append(('Content-Encoding', 'gzip'))
                headers.append(('Vary', 'Accept-Encoding'))
            start_response("200 OK", headers)
            if environ['REQUEST_METHOD'] == 'GET':
                return self._body(full_path, environ, file_like)
            else:
                return ['']
        except (IOError, OSError):
            return self.not_found(environ, start_response)


class Cling(WSGIHandler):
    """WSGI middleware that intercepts calls to the static files
    directory, as defined by the STATIC_URL setting, and serves those files.
    """
    def __init__(self, application, base_dir=None, base_url=None, ignore_debug=False):
        self.application = application
        self.ignore_debug = ignore_debug
        if not base_dir:
            base_dir = self.get_base_dir()
        self.base_url = urlparse(base_url or self.get_base_url())

        self.cling = GzipCling(base_dir)
        try:
            self.debug_cling = DebugHandler(application, base_dir=base_dir)
        except TypeError:
            self.debug_cling = DebugHandler(application)

        super(Cling, self).__init__()

    def get_base_dir(self):
        return settings.STATIC_ROOT

    def get_base_url(self):
        utils.check_settings()
        return settings.STATIC_URL

    @property
    def debug(self):
        return settings.DEBUG

    def _transpose_environ(self, environ):
        """Translates a given environ to static.Cling's expectations."""
        environ['PATH_INFO'] = environ['PATH_INFO'][len(self.base_url[2]) - 1:]
        return environ

    def _should_handle(self, path):
        """Checks if the path should be handled. Ignores the path if:

        * the host is provided as part of the base_url
        * the request's path isn't under the media path (or equal)
        """
        return path.startswith(self.base_url[2]) and not self.base_url[1]

    def __call__(self, environ, start_response):
        # Hand non-static requests to Django
        if not self._should_handle(get_path_info(environ)):
            return self.application(environ, start_response)

        # Serve static requests from static.Cling
        if not self.debug or self.ignore_debug:
            environ = self._transpose_environ(environ)
            return self.cling(environ, start_response)
        # Serve static requests in debug mode from StaticFilesHandler
        else:
            return self.debug_cling(environ, start_response)


class MediaCling(Cling):

    def __init__(self, application, base_dir=None):
        super(MediaCling, self).__init__(application, base_dir=base_dir)
        # override callable attribute with method
        self.debug_cling = self._debug_cling

    def _debug_cling(self, environ, start_response):
        environ = self._transpose_environ(environ)
        return self.cling(environ, start_response)

    def get_base_dir(self):
        return settings.MEDIA_ROOT

    def get_base_url(self):
        return settings.MEDIA_URL
