# -*- coding: utf-8 -*-
#
# Copyright © 2012 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.

import base64
import httplib
import locale
import os
import urllib
from gettext import gettext as _

try:
    import json
except ImportError:
    import simplejson as json

from M2Crypto import SSL, httpslib

from pulp.client.lib.logutil import getLogger, getResponseLogger

# exception classes to handle server request exceptions


class RequestException(Exception):
    """
    Base exception class
    """
    def __init__(self, response_body):
        Exception.__init__(self)
        self.href = response_body['href']
        self.http_status = response_body['http_status']
        self.error_message = response_body['error_message']
        self.exception = response_body['exception']
        self.traceback = response_body['traceback']
        
    def __str__(self):
        return _('RequestException: %s - %s' % (self.http_status, self.error_message))
            

# Response code = 400
class BadRequestException(RequestException): pass

# Response code = 401. Commented out for now until we fix server side exception handling to follow same hierarchy.
# class PermissionsException(RequestException): pass

# Response code = 404
class NotFoundException(RequestException): pass

# Response code = 409
class DuplicateResourceException(RequestException): pass

# Response code >= 500
class PulpServerException(RequestException): pass


class ConnectionException(Exception):
    """
    Exception to indicate a less than favorable response from the server.
    The arguments are [0] the response status as an integer and
    [1] the response message as a dict, if we managed to decode from json,
    or a str if we didn't [2] potentially a traceback, if the server response
    was a python error, otherwise it will be None
    """
    pass

class PermissionsException(Exception):
    """
    Indicates an attempt was made to do a server call without providing
    authentication credentials, either through a certificate or as command
    line flags.
    """
    pass

# server wrapper class which invokes python connection apis and allows us to mock them

class ServerWrapper(object):
    def __init__(self, connection):
        self.connection = connection

    def request(self, method, url, body, headers):
        self.connection.request(method, url, body=body, headers=headers)
        try:
            response = self.connection.getresponse()
        except SSL.SSLError, err:
            raise ConnectionException(None, str(err), None)
        response_body = response.read()
        try:
            response_body = json.loads(response_body)
        except:
            pass
        return response.status, response_body
    
# response classes ------------------------------------------------------------

class Response(object):
    """
    Successful response class
    """
    def __init__(self, response_code, response_body):
        self.response_code = response_code
        self.response_body = response_body
        
    def __str__(self):
        return _("Response:\ncode - %s\nresponse_body - %s\n" % (self.response_code, self.response_body))


class AsyncResponse(Response):
    """
    Async task response class. For now, this is identical to Response class until server side async response is flushed out
    """
    pass

# pulp server class -----------------------------------------------------------

class PulpConnection(object):
    """
    Pulp server connection class.
    """

    def __init__(self, host, port=443, path_prefix='/pulp/api', timeout=120, connection=None,
                 server_wrapper=None, api_responses_log=None, username=None, password=None, certfile=None):

        self.host = host
        self.port = port
        self.path_prefix = path_prefix
        self.headers = {}
        self.timeout = timeout
        self.api_responses_log = api_responses_log

        default_locale = locale.getdefaultlocale()[0]
        if default_locale:
            default_locale = default_locale.lower().replace('_', '-')
        else:
            default_locale = 'en-us'

        headers = {'Accept': 'application/json',
                   'Accept-Language': default_locale,
                   'Content-Type': 'application/json'}
        self.headers.update(headers)

        self._log = getLogger('pulp')

        self.__certfile = None

        if connection:
            self.connection = connection
        else:                
            self.connection = self._https_connection()

        if server_wrapper:
            self.server_wrapper = server_wrapper
        else:
            self.server_wrapper = ServerWrapper(self.connection)

        # set credentials or check if credentials are already set
        if username and password:
            self.set_basic_auth_credentials(username, password)
        elif certfile:
            self.set_ssl_credentials(certfile)
        else:
            pass

    # protected server connection method -------------------------------------

    def _https_connection(self):
        # make sure that passed in username and password overrides cert/key auth
        if self.__certfile is None or \
                'Authorization' in self.headers:
            return httplib.HTTPSConnection(self.host, self.port)
        ssl_context = SSL.Context('sslv3')
        ssl_context.set_session_timeout(self.timeout)
        ssl_context.load_cert(self.__certfile)

        self.connection = httpslib.HTTPSConnection(self.host,
                                        self.port,
                                        ssl_context=ssl_context)


    # protected request utilities ---------------------------------------------

    def _build_url(self, path, queries=()):
        # build the request url from the path and queries dict or tuple
        if not path.startswith(self.path_prefix):
            path = '/'.join((self.path_prefix, path))
        # Check if path is ascii and uses appropriate characters, else convert to binary or unicode as necessary.
        try:
            path = urllib.quote(str(path))
        except UnicodeEncodeError:
            path = urllib.quote(path.encode('utf-8'))
        except UnicodeDecodeError:
            path = urllib.quote(path.decode('utf-8'))
        queries = urllib.urlencode(queries)
        if queries:
            path = '?'.join((path, queries))
        return path


    def _request(self, method, path, queries=(), body=None):
        # make a request to the pulp server and return the response
        # NOTE this throws a ConnectionException or one of the RequestExceptions (depending on response codes) 
        # in case of unsuccessful request
        url = self._build_url(path, queries)
        if not isinstance(body, (type(None), str,)):
            body = json.dumps(body)
        self._log.debug('sending %s request to %s' % (method, url))

        response_code, response_body = self.server_wrapper.request(method=method, url=url,
                                                    body=body, headers=self.headers)

        if self.api_responses_log:
            self._response_log = getResponseLogger('api_responses', self.api_responses_log)
            self._response_log.info('%s request to %s with parameters %s' % (method, url, body))
            self._response_log.info("Response status : %s \n" % response_code)
            self._response_log.info("Response body :\n %s\n" % json.dumps(response_body, indent=2))
                
        if response_code >= 300:
            self.handle_exceptions(response_code, response_body)
        elif response_code == 200:
            return Response(response_code, response_body)
        elif response_code == 201:
            return AsyncResponse(response_code, response_body)

    # Raise appropriate exceptions based on response code

    def handle_exceptions(self, response_code, response_body):
        if response_code == 400:
            raise BadRequestException(response_body)
        elif response_code == 401:
            raise PermissionsException(response_body)
        elif response_code == 404:
            raise NotFoundException(response_body)
        elif response_code == 409:
            raise DuplicateResourceException(response_body)
        else:
            raise PulpServerException(response_body)

    # credentials setters -----------------------------------------------------

    def set_basic_auth_credentials(self, username, password):
        raw = ':'.join((username, password))
        encoded = base64.encodestring(raw)[:-1]
        self.headers['Authorization'] = 'Basic ' + encoded

    def set_ssl_credentials(self, certfile):
        if not os.access(certfile, os.R_OK):
            raise RuntimeError(_('certificate file %s does not exist or cannot be read')
                               % certfile)
        self.__certfile = certfile

    def has_credentials_set(self):
        return 'Authorization' in self.headers or self.__certfile is not None

    # request methods ---------------------------------------------------------

    def DELETE(self, path, body=None):
        return self._request('DELETE', path, body=body)

    def GET(self, path, queries=()):
        return self._request('GET', path, queries)

    def HEAD(self, path):
        return self._request('HEAD', path)

    def POST(self, path, body=None):
        return self._request('POST', path, body=body)

    def PUT(self, path, body):
        return self._request('PUT', path, body=body)