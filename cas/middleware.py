"""CAS authentication middleware"""

try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode
import ssl
import json
import logging
try:
    from urllib import urlopen
except ImportError:
    from urllib.request import urlopen
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth import logout as do_logout
from django.contrib.auth.views import login, logout
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponseForbidden
from django.core.exceptions import ImproperlyConfigured
from django.contrib import auth
try:
    from django.utils.deprecation import MiddlewareMixin
except ImportError:
    MiddlewareMixin = object

from cas.exceptions import CasTicketException
from cas.views import login as cas_login, logout as cas_logout

__all__ = ['CASMiddleware']


class CASMiddleware(MiddlewareMixin):
    """
    Middleware that allows CAS authentication on admin pages
    """
    logger = logging.getLogger(__name__)

    def process_request(self, request):
        """
        Checks that the authentication middleware is installed

        :param: request

        """

        error = ("The Django CAS middleware requires authentication "
                 "middleware to be installed. Edit your MIDDLEWARE_CLASSES "
                 "setting to insert 'django.contrib.auth.middleware."
                 "AuthenticationMiddleware'.")
        assert hasattr(request, 'user'), error

    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        Forwards unauthenticated requests to the admin page to the CAS
        login URL, as well as calls to django.contrib.auth.views.login and
        logout.
        """
        serviceTicket = request.session.get('st')

        if serviceTicket:
            self.logger.debug('service ticket from session: ' + serviceTicket)
        else:
            self.logger.debug("system don't have any service ticket, should go to login page")

        if serviceTicket and settings.CAS_SINGLE_LOGOUT_SERVICE_TICKET_URL != None :
            gcontext = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
            ticketUrl = settings.CAS_SINGLE_LOGOUT_SERVICE_TICKET_URL + serviceTicket
            self.logger.debug('check service ticket expired via url: ' + ticketUrl)
            page = urlopen(ticketUrl, context=gcontext)
            response = page.read()
            self.logger.debug('response: ' + response)
            response = json.loads(response)
            if response['expired'] == True :
                self.logger.debug('service ticket is expired, logout')
                del request.session['st']
                auth.logout(request)
                return None

        if view_func == login:
            return cas_login(request, *view_args, **view_kwargs)
        elif view_func == logout:
            return cas_logout(request, *view_args, **view_kwargs)

        if settings.CAS_ADMIN_PREFIX:
            if not request.path.startswith(settings.CAS_ADMIN_PREFIX):
                return None
        elif not view_func.__module__.startswith('django.contrib.admin.'):
            return None

        if request.user.is_authenticated():
            if request.user.is_staff:
                return None
            else:
                error = ('<h1>Forbidden</h1><p>You do not have staff '
                         'privileges.</p>')
                return HttpResponseForbidden(error)

        params = urlencode({REDIRECT_FIELD_NAME: request.get_full_path()})
        return HttpResponseRedirect(reverse(cas_login) + '?' + params)

    def process_exception(self, request, exception):
        """
        When we get a CasTicketException, that is probably caused by the ticket timing out.
        So logout/login and get the same page again.
        """

        if isinstance(exception, CasTicketException):
            do_logout(request)
            # This assumes that request.path requires authentication.
            return HttpResponseRedirect(request.path)
        else:
            return None


class ProxyMiddleware(MiddlewareMixin):

    # Middleware used to "fake" the django app that it lives at the Proxy Domain
    def process_request(self, request):
        proxy = getattr(settings, 'PROXY_DOMAIN', None)
        if not proxy:
            raise ImproperlyConfigured('To use Proxy Middleware you must set a PROXY_DOMAIN setting.')
        else:
            request.META['HTTP_HOST'] = proxy
