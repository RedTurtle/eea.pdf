""" Download PDF
"""
import logging
from zope import event
from zope.publisher.interfaces import NotFound
from zope.component import queryMultiAdapter, queryUtility
from zope.component.hooks import getSite
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from plone.app.async.interfaces import IAsyncService
from eea.converter.browser.app.download import Pdf
from eea.downloads.interfaces import IStorage
from eea.pdf.config import EEAMessageFactory as _
from eea.pdf.events.sync import PDFExportFail, PDFExportSuccess
from eea.pdf.events.async import AsyncPDFExportSuccess
from eea.pdf import async
logger = logging.getLogger('eea.pdf')

class Download(Pdf):
    """ Download PDF
    """
    template = ViewPageTemplateFile('../zpt/download.pt')
    _message = ''
    _email = ''

    def make_pdf(self, dry_run=False, **kwargs):
        """ Compute pdf
        """
        data = super(Download, self).make_pdf(dry_run=dry_run, **kwargs)

        # Async
        if dry_run:
            return data

        # Sync events
        if not data:
            event.notify(PDFExportFail(self.context))
        event.notify(PDFExportSuccess(self.context))

        return data

    @property
    def message(self):
        """ Message
        """
        return self._message

    @property
    def email(self):
        """ User email
        """
        return self._email

    def _redirect(self, msg=''):
        """ Redirect
        """
        self.request.set('disable_border', 1)
        self.request.set('disable_plone.leftcolumn', 1)
        self.request.set('disable_plone.rightcolumn', 1)
        self._message = msg
        return self.template()

    def link(self):
        """ Download link
        """
        storage = IStorage(self.context).of('pdf')
        return storage.absolute_url()

    def period(self):
        """ Wait period
        """
        ptype = getattr(self.context, 'portal_type', '')
        if ptype.lower() in ('collection', 'topic', 'folder', 'atfolder'):
            return _(u"minutes")
        return _(u"seconds")

    def finish(self, email=''):
        """ Finish download
        """
        self._email = email
        return self._redirect(_(
            u"The PDF is being generated. "
            u"An email will be sent to you when the PDF is ready. "
            u"If you don't have access to your email address "
            u"check <a href='${link}'>this link</a> in a few ${period}.",
            mapping={
                "link": self.link(),
                "period": self.period()
            }
        ))

    def download(self, email='', **kwargs):
        """ Download
        """
        # PDF already generated
        storage = IStorage(self.context).of('pdf')
        filepath = storage.filepath()
        fileurl = storage.absolute_url()
        url = self.context.absolute_url()
        title = self.context.title_or_id()

        portal = getSite()
        from_name = portal.getProperty('email_from_name')
        from_email = portal.getProperty('email_from_address')

        if async.file_exists(filepath):
            wrapper = async.ContextWrapper(self.context)(
                fileurl=fileurl,
                filepath=filepath,
                email=email,
                url=url,
                from_name=from_name,
                from_email=from_email,
                title=title
            )

            event.notify(AsyncPDFExportSuccess(wrapper))
            return self.finish(email=email)

        # Cheat condition @@plone_context_state/is_view_template
        self.request['ACTUAL_URL'] = self.context.absolute_url()

        # Async generate PDF
        converter = self.make_pdf(dry_run=True)
        worker = queryUtility(IAsyncService)
        worker.queueJob(
            async.make_async_pdf,
            self.context, converter,
            email=email,
            filepath=filepath,
            fileurl=fileurl,
            url=url,
            from_name=from_name,
            from_email=from_email,
            title=title
        )

        return self.finish(email=email)

    def post(self, **kwargs):
        """ POST
        """
        if not self.request.get('form.button.download'):
            return self._redirect('Invalid form')

        email = self.request.get('email')

        # Filter bots
        if self.request.get('body'):
            return self.finish(email=email)

        if not email:
            return self.finish(email=email)

        return self.download(email, **kwargs)

    def __call__(self, **kwargs):
        support = queryMultiAdapter((self.context, self.request),
                                    name='pdf.support')

        # Check for permission
        if not getattr(support, 'can_download', lambda: False)():
            raise NotFound(self.context, self.__name__, self.request)

        # Don't download PDF asynchronously
        if not support.async():
            return super(Download, self).__call__(**kwargs)

        # We have the email, continue
        email = getattr(support, 'email', lambda: None)()
        if email:
            return self.download(email, **kwargs)

        # Email provided
        if self.request.method.lower() == 'post':
            return self.post(**kwargs)

        # Ask for email
        return self._redirect()
