"""Public content, navigation, assets, and workspace integration checks."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse
from PIL import Image


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


class PageMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.images = []
        self.ids = set()
        self.buttons = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get('id'):
            self.ids.add(attributes['id'])
        if tag == 'a':
            self.links.append(attributes)
        elif tag == 'img':
            self.images.append(attributes)
        elif tag == 'button' and attributes.get('id'):
            self.buttons[attributes['id']] = attributes


@override_settings(STORAGES=TEST_STORAGES)
class PublicPageTests(SimpleTestCase):
    pages = {
        'public_home': ('/', 'home.html'),
        'user_guide': ('/guide/', 'guide.html'),
        'about': ('/about/', 'about.html'),
        'contact': ('/contact/', 'contact.html'),
        'privacy': ('/privacy/', 'privacy.html'),
        'terms': ('/terms/', 'terms.html'),
    }

    def test_public_routes_render_shared_templates_without_creating_sessions(self):
        for name, (path, template) in self.pages.items():
            with self.subTest(page=name):
                self.assertEqual(reverse(f'core:{name}'), path)
                self.assertEqual(resolve(path).view_name, f'core:{name}')
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, f'core/public/{template}')
                self.assertTemplateUsed(response, 'base.html')
                self.assertTemplateUsed(response, 'core/includes/navigation.html')
                self.assertTemplateUsed(response, 'core/includes/footer.html')
                self.assertFalse(response.wsgi_request.session.modified)
                self.assertEqual(dict(response.cookies), {})
                self.assertContains(response, 'href="#main-content"')
                self.assertContains(response, 'id="main-content"')
                head = self.client.head(path)
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b'')

    def test_shared_navigation_footer_and_contact_links(self):
        names = ['public_home', 'home', 'user_guide', 'about', 'contact', 'privacy', 'terms']
        for name in self.pages:
            with self.subTest(page=name):
                html = self.client.get(reverse(f'core:{name}')).content.decode()
                links = {link.get('href') for link in PageMarkup(html).links}
                for destination in names:
                    self.assertIn(reverse(f'core:{destination}'), links)
                self.assertIn('mailto:ayenimichael92@gmail.com', links)
                self.assertIn('https://github.com/Granzular', links)
                self.assertIn('aria-controls="site-links"', html)
                self.assertIn('aria-current="page"', html)

    def test_workspace_route_and_landing_calls_to_action(self):
        self.assertEqual(reverse('core:public_home'), '/')
        self.assertEqual(reverse('core:home'), '/workspace/')
        self.assertEqual(resolve('/workspace/').view_name, 'core:home')
        self.assertRedirects(
            self.client.get('/workspace'), '/workspace/',
            status_code=301, fetch_redirect_response=False,
        )
        html = self.client.get(reverse('core:public_home')).content.decode()
        markup = PageMarkup(html)
        calls_to_action = [link for link in markup.links if 'site-button' in link.get('class', '')]
        self.assertEqual(
            [link['href'] for link in calls_to_action],
            ['/workspace/', '/workspace/'],
        )
        self.assertIn('#how-it-works', {link.get('href') for link in markup.links})
        self.assertIn('how-it-works', markup.ids)
        self.assertNotIn('native deterministic', html.lower())
        self.assertNotIn('engine selector', html.lower())

    def test_old_public_home_paths_are_removed(self):
        for path in ('/home', '/home/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_screenshot_extensions_discovery_dimensions_and_alt_text(self):
        sizes = {'1': (1366, 659), '2': (1366, 641), '3': (1295, 217)}
        for number, size in sizes.items():
            path = finders.find(f'media/screenshot-{number}.PNG')
            self.assertIsNotNone(path)
            self.assertEqual(Path(path).name, f'screenshot-{number}.PNG')
            with Image.open(path) as screenshot:
                self.assertEqual(screenshot.size, size)
                self.assertEqual(screenshot.format, 'PNG')
        for name in ('public_home', 'user_guide'):
            markup = PageMarkup(self.client.get(reverse(f'core:{name}')).content.decode())
            sources = {image['src'] for image in markup.images}
            for number in sizes:
                self.assertIn(f'/static/media/screenshot-{number}.PNG', sources)
            for image in markup.images:
                self.assertTrue(image.get('alt'))
                self.assertTrue(image.get('width'))
                self.assertTrue(image.get('height'))

    def test_internal_links_and_guide_anchors_have_destinations(self):
        rendered = {
            path: PageMarkup(self.client.get(path).content.decode())
            for path, _ in self.pages.values()
        }
        for path, markup in rendered.items():
            for link in markup.links:
                destination = urlsplit(link.get('href', ''))
                if destination.scheme or destination.path.startswith('/static/'):
                    continue
                with self.subTest(page=path, link=link.get('href')):
                    target = destination.path or path
                    resolve(target)
                    if destination.fragment:
                        self.assertIn(destination.fragment, rendered[target].ids)

    @override_settings(
        ARTIFACT_TTL_SECONDS=333, SESSION_COOKIE_AGE=7200,
        SESSION_COOKIE_NAME='course_session', CSRF_COOKIE_NAME='course_csrf',
        EXECUTION_TIMEOUT_SECONDS='42',
    )
    def test_privacy_and_guide_reflect_configured_lifetimes(self):
        privacy = self.client.get(reverse('core:privacy'))
        self.assertContains(privacy, '333 seconds after creation')
        self.assertContains(privacy, '7200 seconds')
        self.assertContains(privacy, 'course_session')
        self.assertContains(privacy, 'course_csrf')
        self.assertContains(privacy, 'full submitted MATLAB source')
        self.assertContains(privacy, 'expired files can remain')
        self.assertContains(privacy, 'SQLite or PostgreSQL')
        self.assertContains(privacy, 'plottwist.workspaceTour.v1')
        self.assertContains(privacy, 'not a complete sandbox')
        guide = self.client.get(reverse('core:user_guide'))
        self.assertContains(guide, '333 seconds')
        self.assertContains(guide, '42 seconds')
        self.assertContains(guide, 'no translation engine selector')
        self.assertContains(guide, 'generated.m')
        self.assertContains(guide, 'generated.py')
        self.assertContains(guide, 'Unsubmitted editor changes')

    def test_public_pages_do_not_accept_code_submissions(self):
        for name in self.pages:
            with self.subTest(page=name):
                response = self.client.post(reverse(f'core:{name}'), {'matlab_code': 'plot(1);'})
                self.assertEqual(response.status_code, 405)


@override_settings(STORAGES=TEST_STORAGES)
class WorkspaceTourTemplateTests(TestCase):
    def test_tour_is_an_optional_enhancement_of_the_existing_workspace(self):
        response = self.client.get(reverse('core:home'))
        self.assertEqual(response.wsgi_request.path, '/workspace/')
        html = response.content.decode()
        markup = PageMarkup(html)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/workspace.html')
        self.assertTemplateUsed(response, 'core/includes/tour.html')
        for element in ('run-form', 'matlab-code', 'run-button', 'python-panel',
                        'figure-workspace', 'command-panel', 'workspace-tour', 'tour-invitation'):
            self.assertIn(element, markup.ids)
        self.assertContains(response, f'action="{reverse("core:run")}" method="post"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, '/static/js/workspace.js')
        self.assertContains(response, '/static/js/workspace-tour.js')
        self.assertIn('hidden', markup.buttons['tour-replay'])
        self.assertContains(response, 'aria-modal="false"')
        self.assertContains(response, 'id="workspace-tour"')
        self.assertNotContains(response, '<select')
        self.assertEqual(set(self.client.session.keys()), {'plottwist_owner'})
        self.assertEqual(response['Cache-Control'], 'private, no-store')
