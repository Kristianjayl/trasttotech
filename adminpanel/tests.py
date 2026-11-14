from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from kiosk.models import BottleRate, CollectionEntry, TinCanRate

from .models import StaffProfile


class CollectionRateDashboardTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="dashboard-admin",
            password="test-password",
        )
        StaffProfile.objects.create(
            user=self.staff,
            role=StaffProfile.ADMIN,
        )
        self.client.force_login(self.staff)

        BottleRate.objects.create(
            points_per_bottle=5,
            market_price_per_kg=Decimal("8.50"),
        )
        TinCanRate.objects.create(
            points_per_tin_can=5,
            market_price_per_kg=Decimal("11.00"),
        )

        CollectionEntry.objects.create(
            weight_kg=1.5,
            material_type=CollectionEntry.PLASTIC_BOTTLE,
        )
        CollectionEntry.objects.create(
            weight_kg=2.0,
            material_type=CollectionEntry.TIN_CAN,
        )

    def test_overview_shows_today_and_month_collection_weight(self):
        response = self.client.get("/staff/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["today_plastic_kg"], Decimal("1.50"))
        self.assertEqual(response.context["today_tin_can_kg"], Decimal("2.00"))
        self.assertEqual(response.context["today_total_kg"], Decimal("3.50"))
        self.assertEqual(response.context["month_total_kg"], Decimal("3.50"))

    def test_reports_use_current_market_prices_for_estimate(self):
        response = self.client.get("/staff/reports/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["plastic_value"], Decimal("12.750"))
        self.assertEqual(response.context["tin_can_value"], Decimal("22.000"))
        self.assertEqual(
            response.context["total_collection_value"],
            Decimal("34.750"),
        )

    def test_rates_page_saves_market_prices(self):
        response = self.client.post(
            "/staff/rates/",
            {
                "points_per_bottle": 5,
                "plastic_price_per_kg": "9.25",
                "points_per_tin_can": 5,
                "tin_can_price_per_kg": "12.50",
            },
        )

        self.assertRedirects(response, "/staff/rates/")
        self.assertEqual(
            BottleRate.objects.get().market_price_per_kg,
            Decimal("9.25"),
        )
        self.assertEqual(
            TinCanRate.objects.get().market_price_per_kg,
            Decimal("12.50"),
        )

    def test_staff_can_record_a_fractional_collection_weight(self):
        response = self.client.post(
            "/staff/collections/",
            {
                "material_type": CollectionEntry.TIN_CAN,
                "weight_kg": "0.50",
                "note": "Afternoon collection",
            },
        )

        self.assertRedirects(response, "/staff/collections/")
        entry = CollectionEntry.objects.get(note="Afternoon collection")
        self.assertEqual(entry.weight_kg, Decimal("0.50"))
