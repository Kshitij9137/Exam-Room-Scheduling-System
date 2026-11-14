from django.test import TestCase


class HomeViewTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "System status")

    def test_admin_login_page_loads(self):
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)
