'''
dav.py

Copyright 2006 Andres Riancho

This file is part of w3af, w3af.sourceforge.net .

w3af is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation version 2 of the License.

w3af is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with w3af; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

'''
import core.data.constants.severity as severity

from core.data.bloomfilter.scalable_bloom import ScalableBloomFilter
from core.data.fuzzer.utils import rand_alpha, rand_alnum
from core.data.dc.headers import Headers
from core.data.kb.vuln import Vuln
from core.data.kb.info import Info
from core.controllers.plugins.audit_plugin import AuditPlugin


class dav(AuditPlugin):
    '''
    Verify if the WebDAV module is properly configured.

    @author: Andres Riancho (andres.riancho@gmail.com)
    '''

    def __init__(self):
        AuditPlugin.__init__(self)

        # Internal variables
        self._already_tested_dirs = ScalableBloomFilter()

    def audit(self, freq, orig_response):
        '''
        Searches for file upload vulns using PUT method.

        @param freq: A FuzzableRequest
        '''
        # Start
        domain_path = freq.get_url().get_domain_path()
        if domain_path not in self._already_tested_dirs:
            self._already_tested_dirs.add(domain_path)
            #
            #    Send the three requests in different threads, store the
            #    apply_result objects in order to be able to "join()" in the
            #    next for loop
            #
            #    TODO: This seems to be a fairly common use case: Send args to N
            #    functions that need to be run in different threads. If possible
            #    code this into threadpool.py in order to make this code clearer
            results = []
            for func in [self._PUT, self._PROPFIND, self._SEARCH]:
                apply_res = self.worker_pool.apply_async(func,
                                                         (domain_path,))
                results.append(apply_res)

            for apply_res in results:
                apply_res.get()

    #pylint: disable=C0103
    def _SEARCH(self, domain_path):
        '''
        Test SEARCH method.
        '''
        content = "<?xml version='1.0'?>\r\n"
        content += "<g:searchrequest xmlns:g='DAV:'>\r\n"
        content += "<g:sql>\r\n"
        content += "Select 'DAV:displayname' from scope()\r\n"
        content += "</g:sql>\r\n"
        content += "</g:searchrequest>\r\n"

        res = self._uri_opener.SEARCH(domain_path, data=content)

        content_matches = '<a:response>' in res or '<a:status>' in res or \
            'xmlns:a="DAV:"' in res

        if content_matches and res.get_code() in xrange(200, 300):
            msg = 'Directory listing with HTTP SEARCH method was found at' \
                  'directory: "%s".' % domain_path
                  
            v = Vuln('Insecure DAV configuration', msg, severity.MEDIUM,
                     res.id, self.get_name())

            v.set_url(res.get_url())
            v.set_method('SEARCH')
            
            self.kb_append(self, 'dav', v)

    #pylint: disable=C0103
    def _PROPFIND(self, domain_path):
        '''
        Test PROPFIND method
        '''
        content = "<?xml version='1.0'?>\r\n"
        content += "<a:propfind xmlns:a='DAV:'>\r\n"
        content += "<a:prop>\r\n"
        content += "<a:displayname:/>\r\n"
        content += "</a:prop>\r\n"
        content += "</a:propfind>\r\n"

        hdrs = Headers([('Depth', '1')])
        res = self._uri_opener.PROPFIND(
            domain_path, data=content, headers=hdrs)

        if "D:href" in res and res.get_code() in xrange(200, 300):
            msg = 'Directory listing with HTTP PROPFIND method was found at' \
                  ' directory: "%s".' % domain_path

            v = Vuln('Insecure DAV configuration', msg, severity.MEDIUM,
                     res.id, self.get_name())

            v.set_url(res.get_url())
            v.set_method('PROPFIND')

            self.kb_append(self, 'dav', v)

    #pylint: disable=C0103
    def _PUT(self, domain_path):
        '''
        Tests PUT method.
        '''
        # upload
        url = domain_path.url_join(rand_alpha(5))
        rnd_content = rand_alnum(6)
        put_response = self._uri_opener.PUT(url, data=rnd_content)

        # check if uploaded
        res = self._uri_opener.GET(url, cache=True)
        if res.get_body() == rnd_content:
            msg = 'File upload with HTTP PUT method was found at resource:' \
                  ' "%s". A test file was uploaded to: "%s".'
            msg = msg % (domain_path, res.get_url())
            
            v = Vuln('Insecure DAV configuration', msg, severity.HIGH,
                     [put_response.id, res.id], self.get_name())

            v.set_url(url)
            v.set_method('PUT')
            
            self.kb_append(self, 'dav', v)

        # Report some common errors
        elif put_response.get_code() == 500:
            msg = 'DAV seems to be incorrectly configured. The web server' \
                  ' answered with a 500 error code. In most cases, this means'\
                  ' that the DAV extension failed in some way. This error was'\
                  ' found at: "%s".' % put_response.get_url()

            i = Info('DAV incorrect configuration', msg, res.id, self.get_name())

            i.set_url(url)
            i.set_method('PUT')
            
            self.kb_append(self, 'dav', i)

        # Report some common errors
        elif put_response.get_code() == 403:
            msg = 'DAV seems to be correctly configured and allowing you to'\
                  ' use the PUT method but the directory does not have the'\
                  ' correct permissions that would allow the web server to'\
                  ' write to it. This error was found at: "%s".'
            msg = msg % put_response.get_url()
            
            i = Info('DAV incorrect configuration', msg,
                     [put_response.id, res.id], self.get_name())

            i.set_url(url)
            i.set_method('PUT')
            
            self.kb_append(self, 'dav', i)

    def get_plugin_deps(self):
        '''
        @return: A list with the names of the plugins that should be run before
                 the current one.
        '''
        return ['infrastructure.allowed_methods',
                'infrastructure.server_header']

    def get_long_desc(self):
        '''
        @return: A DETAILED description of the plugin functions and features.
        '''
        return '''
        This plugin finds WebDAV configuration errors. These errors are generally
        server configuration errors rather than a web application errors. To
        check for vulnerabilities of this kind, the plugin will try to PUT a
        file on a directory that has WebDAV enabled, if the file is uploaded
        successfully, then we have found a bug.
        '''
