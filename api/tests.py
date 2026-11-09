"""
Run:  python manage.py test api
"""
import os
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from app1.models import Event, Memory, Profile
from family.models import LonappanFamily, VarunnyFamily

from api import otp as otp_mod
from api.models import ChangeRequest, FaceProfile, MemberLink, NewMemberRequest, Notification, PhoneOTP
from api.people import describe

os.environ["EXPO_PUSH"] = "0"
User = get_user_model()


def code_for(phone):
    """Tests can't read SMS — generate a known code by patching the sender."""
    sent = {}

    def fake_send(p, c):
        sent["code"] = c
    original = otp_mod.send_sms_code
    otp_mod.send_sms_code = fake_send
    try:
        otp_mod.create_and_send(phone)
    finally:
        otp_mod.send_sms_code = original
    return sent["code"]


class ApiFlowTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # reset rate limits between tests
        L = LonappanFamily
        self.founder = L.objects.create(first_name="Lonappan", last_name="M", gender="M", membership_category="NM")
        self.joseph = L.objects.create(first_name="Joseph", last_name="L", gender="M", parent=self.founder,
                                       membership_category="LM")
        self.rosa = L.objects.create(first_name="Rosa", last_name="L", gender="F", parent=self.founder,
                                     membership_category="NM")
        self.anil = L.objects.create(first_name="Anil", last_name="Joseph", gender="M", parent=self.joseph,
                                     membership_category="LM", blood_group="O+", mobile_number="9876543210",
                                     date_of_birth=date.today().replace(year=1976))
        self.thomas = L.objects.create(first_name="Thomas", last_name="Joseph", gender="M", parent=self.joseph,
                                       membership_category="LM")
        self.neha = L.objects.create(first_name="Neha", last_name="Thomas", gender="F", parent=self.thomas,
                                     membership_category="NM")
        self.reena = L.objects.create(first_name="Reena", last_name="Anil", gender="F", membership_category="NM")
        self.reena.spouses.add(self.anil)
        self.staff = User.objects.create_user("secretary", password="Str0ng-pass!", is_staff=True)
        self.c = APIClient()

    def login_phone(self, phone="9876500001", name="Riya Thomas"):
        code = code_for(otp_mod.normalize_phone(phone))
        r = self.c.post("/api/auth/otp/verify", {"phone": phone, "code": code, "name": name}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + r.data["access"])
        return r.data

    def login_staff(self):
        r = self.c.post("/api/auth/login", {"username": "secretary", "password": "Str0ng-pass!"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + r.data["access"])

    # ── Auth ────────────────────────────────────────────────
    def test_phone_normalize(self):
        self.assertEqual(otp_mod.normalize_phone("98765 43210"), "+919876543210")
        self.assertEqual(otp_mod.normalize_phone("+91-98765-43210"), "+919876543210")
        self.assertEqual(otp_mod.normalize_phone("123"), "")

    def test_wrong_code_counts_attempts(self):
        phone = "+919876500002"
        code_for(phone)
        r = self.c.post("/api/auth/otp/verify", {"phone": phone, "code": "000000"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(PhoneOTP.objects.get(phone=phone).attempts, 1)

    def test_new_user_is_pending_and_blocked(self):
        data = self.login_phone()
        self.assertTrue(data["created"])
        self.assertEqual(data["me"]["status"], "pending")
        self.assertEqual(self.c.get("/api/members").status_code, 403)
        r = self.c.post("/api/me/claim", {"branch": "lonappan", "text": "wife of Jeevan"}, format="json")
        self.assertEqual(r.data["claim"]["branch"], "lonappan")

    def test_signup_approval_flow(self):
        data = self.login_phone()
        uid = data["me"]["id"]
        self.c.post("/api/me/claim", {"branch": "lonappan", "text": "daughter-in-law"}, format="json")
        self.login_staff()
        r = self.c.get("/api/admin/approvals")
        self.assertEqual(r.data["count"], 1)
        r = self.c.post(f"/api/admin/approvals/signup/{uid}/approve",
                        {"member_ref": f"lonappan:{self.reena.pk}"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Profile.objects.get(user_id=uid).is_approved)
        self.assertEqual(MemberLink.objects.get(user_id=uid).member_id, self.reena.pk)
        self.assertTrue(Notification.objects.filter(user_id=uid, kind="approval").exists())

    def test_existing_phone_logs_into_existing_account(self):
        u = User.objects.create_user("old")
        Profile.objects.create(user=u, full_name="Old Member", phone_number="98765 00003", is_approved=True)
        data = self.login_phone("+91 98765 00003")
        self.assertFalse(data["created"])
        self.assertEqual(data["me"]["status"], "approved")

    # ── Family ──────────────────────────────────────────────
    def test_search_tree_detail(self):
        self.login_staff()
        r = self.c.get("/api/members", {"q": "anil"})
        names = [x["name"] for x in r.data["results"]]
        self.assertIn("Anil Joseph", names)
        r = self.c.get("/api/tree/lonappan", {"depth": 4})
        root = r.data["roots"][0]
        self.assertEqual(root["name"], "Lonappan M")
        self.assertEqual(root["children_count"], 2)
        r = self.c.get(f"/api/members/lonappan/{self.anil.pk}")
        self.assertEqual(r.data["parent"]["name"], "Joseph L")
        self.assertEqual(r.data["spouses"][0]["name"], "Reena Anil")
        self.assertEqual(r.data["mobile"], "9876543210")  # staff can see phones

    def test_relationships(self):
        self.login_staff()
        get = lambda a, b: self.c.get("/api/relationship", {"a": f"lonappan:{a.pk}", "b": f"lonappan:{b.pk}"}).data
        self.assertEqual(get(self.anil, self.neha)["relation"], "Niece")
        self.assertEqual(get(self.anil, self.rosa)["relation"], "Aunt")
        self.assertEqual(get(self.anil, self.thomas)["relation"], "Brother")
        self.assertEqual(get(self.neha, self.founder)["relation"], "Great-grandfather")
        self.assertEqual(get(self.anil, self.reena)["relation"], "Wife")
        self.assertIn("by marriage", get(self.reena, self.thomas)["relation"])
        v = VarunnyFamily.objects.create(first_name="Jomon", last_name="V")
        self.assertFalse(self.c.get("/api/relationship", {"a": f"lonappan:{self.anil.pk}", "b": f"varunny:{v.pk}"}).data["found"])

    def test_describe_cousins(self):
        self.assertEqual(describe(2, 2, "M"), "First cousin")
        self.assertEqual(describe(3, 3, "F"), "Second cousin")
        self.assertEqual(describe(2, 3, "F"), "First cousin once removed")

    def test_today_birthdays(self):
        self.login_staff()
        r = self.c.get("/api/today")
        self.assertEqual(r.data["birthdays"][0]["name"], "Anil Joseph")

    def test_change_request_approved_applies(self):
        self.login_staff()
        r = self.c.post("/api/requests/change", {"member_ref": f"lonappan:{self.neha.pk}",
                                                 "field": "date_of_birth", "value": "2001-10-19"}, format="json")
        self.assertEqual(r.status_code, 201)
        cid = r.data["id"]
        r = self.c.post(f"/api/admin/approvals/change/{cid}/approve", {}, format="json")
        self.assertEqual(r.data["status"], "approved")
        self.neha.refresh_from_db()
        self.assertEqual(self.neha.date_of_birth, date(2001, 10, 19))
        bad = self.c.post("/api/requests/change", {"member_ref": f"lonappan:{self.neha.pk}",
                                                   "field": "membership_category", "value": "LM"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_new_child_request(self):
        self.login_staff()
        r = self.c.post("/api/requests/new-member", {"relative_ref": f"lonappan:{self.anil.pk}", "relation": "child",
                                                     "first_name": "Ethan", "last_name": "Anil", "gender": "M",
                                                     "date_of_birth": "2026-10-05"}, format="json")
        rid = r.data["id"]
        r = self.c.post(f"/api/admin/approvals/new_member/{rid}/approve", {}, format="json")
        self.assertEqual(r.data["member"]["generation"], 4)
        self.assertEqual(NewMemberRequest.objects.get(pk=rid).status, "approved")
        self.assertTrue(LonappanFamily.objects.filter(first_name="Ethan", parent=self.anil).exists())

    # ── Membership numbers never repeat ─────────────────────
    def test_membership_number_after_delete(self):
        a = LonappanFamily.objects.create(first_name="A", last_name="X", membership_category="PM")
        b = LonappanFamily.objects.create(first_name="B", last_name="X", membership_category="PM")
        a.delete()
        c = LonappanFamily.objects.create(first_name="C", last_name="X", membership_category="PM")
        self.assertNotEqual(b.membership_number, c.membership_number)
        self.assertEqual(c.membership_number, "PM0003")
        nm = LonappanFamily.objects.create(first_name="N", last_name="X", membership_category="NM")
        self.assertIsNone(nm.membership_number)

    # ── Events & community ──────────────────────────────────
    def test_event_rsvp(self):
        e = Event.objects.create(title="Annual Meet", category="association",
                                 date=date.today() + timedelta(days=30), rsvp_enabled=True, location="Thrissur")
        self.login_staff()
        r = self.c.post(f"/api/events/{e.pk}/rsvp", {"people": 4}, format="json")
        self.assertEqual(r.data["going_people"], 4)
        r = self.c.get("/api/events")
        self.assertEqual(r.data[0]["my_rsvp"]["people"], 4)

    def test_memory_prayer(self):
        m = Memory.objects.create(name="Paul", birth_date=date(1940, 1, 1), death_date=date(2015, 10, 17),
                                  image="memory_images/x.png", description="Teacher")
        self.login_staff()
        r = self.c.post(f"/api/memories/{m.pk}")
        self.assertEqual(r.data["prayers"], 1)
        self.assertTrue(r.data["prayed"])

    def test_blood_request_and_respond(self):
        self.login_staff()
        r = self.c.post("/api/blood-requests", {"blood_group": "b+", "hospital": "Amala", "units": 2}, format="json")
        self.assertEqual(r.status_code, 201)
        bid = r.data["id"]
        r = self.c.post(f"/api/blood-requests/{bid}/respond")
        self.assertEqual(r.data["donors_confirmed"], 1)
        r = self.c.get("/api/blood-donors", {"group": "O+"})
        self.assertEqual(r.data[0]["name"], "Anil Joseph")
        self.assertTrue(r.data[0]["can_give"])
        r = self.c.get("/api/blood-donors")
        self.assertEqual(r.data["counts"]["O+"], 1)

    def test_search_shows_relation_to_me(self):
        data = self.login_phone()
        from api.models import MemberLink
        Profile.objects.filter(user_id=data["me"]["id"]).update(is_approved=True)
        MemberLink.objects.update_or_create(user_id=data["me"]["id"], defaults={"branch": "lonappan", "member_id": self.anil.pk})
        r = self.c.get("/api/members", {"q": "Thomas"})
        rel = {x["first_name"]: x.get("relation_to_me") for x in r.data["results"]}
        self.assertEqual(rel["Thomas"], "Brother")
        r = self.c.get("/api/members", {"q": "Anil"})
        self.assertEqual(r.data["results"][0]["relation_to_me"], "You")
        r = self.c.get("/api/me")
        self.assertFalse(r.data["fee"]["paid"])
        self.assertTrue(r.data["fee"]["life_member"])
        self.assertIn("photo", r.data["missing_details"])

    # ── Admin ───────────────────────────────────────────────
    def test_admin_requires_staff(self):
        self.login_phone()
        self.assertEqual(self.c.get("/api/admin/dashboard").status_code, 403)

    def test_dashboard_and_member_crud(self):
        self.login_staff()
        r = self.c.get("/api/admin/dashboard")
        self.assertEqual(r.data["members"]["total"], 7)
        lon = next(b for b in r.data["branches"] if b["slug"] == "lonappan")
        self.assertIn("app_users", lon)
        self.assertIn("living", lon)
        r = self.c.post("/api/admin/members/lonappan", {"first_name": "Aaron", "last_name": "Anil", "gender": "M",
                                                         "parent": self.anil.pk, "membership_category": "NM"},
                        format="json")
        self.assertEqual(r.status_code, 201, r.content)
        new_id = r.data["id"]
        r = self.c.patch(f"/api/admin/members/lonappan/{new_id}", {"blood_group": "A+"}, format="json")
        self.assertEqual(r.data["blood_group"], "A+")
        r = self.c.delete(f"/api/admin/members/lonappan/{self.joseph.pk}")
        self.assertEqual(r.status_code, 400)  # has children
        self.assertEqual(self.c.delete(f"/api/admin/members/lonappan/{new_id}").status_code, 204)

    def test_broadcast_and_payment(self):
        data = self.login_phone()
        Profile.objects.filter(user_id=data["me"]["id"]).update(is_approved=True)
        self.login_staff()
        r = self.c.post("/api/admin/broadcast", {"audience": "all", "message": "Hello family"}, format="json")
        self.assertEqual(r.data["recipients"], 2)  # the approved member + the secretary
        r = self.c.post("/api/admin/broadcast", {"audience": "all", "message": "Dear {first name}, hello"}, format="json")
        self.assertEqual(r.data["recipients"], 2)
        from api.models import Notification
        self.assertFalse(Notification.objects.filter(body__contains="{first name}").exists())
        r = self.c.post("/api/admin/payments", {"payer_name": "Anil", "purpose": "donation", "amount": "1000",
                                                "method": "upi"}, format="json")
        self.assertEqual(r.data["receipt_no"], "RC-0001")
        r = self.c.get("/api/admin/payments")
        self.assertEqual(r.data["total_amount"], "1000.00")


class DashboardExtrasTests(TestCase):
    """Settings, committee list, photos and dashboard numbers used by the new dashboard."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.staff = User.objects.create_user("secretary", password="Str0ng-pass!", is_staff=True)
        self.c = APIClient()
        r = self.c.post("/api/auth/login", {"username": "secretary", "password": "Str0ng-pass!"}, format="json")
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + r.json()["access"])

    def test_settings_roundtrip(self):
        r = self.c.get("/api/admin/settings")
        self.assertEqual(r.json()["app_name"], "Vamsham")
        r = self.c.patch("/api/admin/settings", {"upi_id": "family@sbi", "annual_fee": "1200.00"}, format="json")
        self.assertEqual(r.status_code, 200)
        r = self.c.get("/api/settings")
        self.assertEqual(r.json()["upi_id"], "family@sbi")
        self.assertEqual(r.json()["annual_fee"], "1200.00")
        self.assertNotIn("receipt_address", r.json())

    def test_committee_and_dashboard(self):
        r = self.c.get("/api/admin/committee")
        self.assertEqual(r.json()[0]["username"], "secretary")
        self.assertTrue(r.json()[0]["is_me"])
        d = self.c.get("/api/admin/dashboard").json()
        for key in ("payments", "new_app_users_this_month", "upcoming_events", "generations", "settings"):
            self.assertIn(key, d)

    def test_photo_upload_and_delete(self):
        import io
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(buf, "JPEG")
        e = Event.objects.create(title="Meet", category="Family", date=date.today())
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            f = SimpleUploadedFile("a.jpg", buf.getvalue(), content_type="image/jpeg")
            r = self.c.post("/api/admin/photos", {"photos": [f], "event": e.id}, format="multipart")
            self.assertEqual(r.status_code, 201, r.content)
            pid = r.json()["photos"][0]["id"]
            albums = self.c.get("/api/admin/photos").json()
            self.assertEqual(albums[0]["count"], 1)
            bad = SimpleUploadedFile("a.txt", b"hi", content_type="text/plain")
            self.assertEqual(self.c.post("/api/admin/photos", {"photos": [bad], "year": "2024"}, format="multipart").status_code, 400)
            self.assertEqual(self.c.delete(f"/api/admin/photos/event/{pid}").status_code, 204)

    def test_members_cannot_use_admin(self):
        self.c.credentials()
        self.assertEqual(self.c.get("/api/admin/settings").status_code, 401)


class DashboardPageTests(TestCase):
    """Django serves the built web dashboard at /dashboard/."""

    def test_dashboard_routes(self):
        import tempfile
        from pathlib import Path
        from vamshamproject import dashboard
        r = self.client.get("/dashboard/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/dashboard/admin")
        with tempfile.TemporaryDirectory() as d:
            old = dashboard.DASHBOARD_DIR
            dashboard.DASHBOARD_DIR = Path(d).resolve()
            try:
                self.assertEqual(self.client.get("/dashboard/admin").status_code, 503)  # not built yet
                (Path(d) / "index.html").write_text("<html>dash</html>")
                (Path(d) / "app.js").write_text("console.log(1)")
                self.assertContains(self.client.get("/dashboard/admin/members/aipu/3"), "dash")
                self.assertEqual(self.client.get("/dashboard/app.js").status_code, 200)
                self.assertEqual(self.client.get("/dashboard/missing.js").status_code, 404)
                self.assertEqual(self.client.get("/dashboard/../manage.py").status_code, 404)
            finally:
                dashboard.DASHBOARD_DIR = old


class BranchManagementTests(TestCase):
    """The committee creates, renames, hides and deletes branches; new branches hold people."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        User.objects.create_user("secretary", password="Str0ng-pass!", is_staff=True)
        self.c = APIClient()
        r = self.c.post("/api/auth/login", {"username": "secretary", "password": "Str0ng-pass!"}, format="json")
        self.c.credentials(HTTP_AUTHORIZATION="Bearer " + r.data["access"])

    def test_original_branches_are_seeded(self):
        r = self.c.get("/api/admin/branches")
        slugs = [b["slug"] for b in r.data]
        self.assertIn("aipu", slugs)
        self.assertEqual(len(slugs), 9)
        self.assertTrue(all(b["original"] for b in r.data))

    def test_create_branch_add_people_tree_and_delete(self):
        r = self.c.post("/api/admin/branches", {"name": "Kunjila"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        slug = r.data["slug"]
        self.assertEqual(slug, "kunjila")
        self.assertEqual(self.c.post("/api/admin/branches", {"name": "kunjila"}, format="json").status_code, 400)

        # people in the new branch
        r = self.c.post(f"/api/admin/members/{slug}", {"first_name": "Mathew", "last_name": "Kunjila", "gender": "M",
                                                       "membership_category": "LM"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        dad = r.data["id"]
        r = self.c.post(f"/api/admin/members/{slug}", {"first_name": "Ethan", "last_name": "Kunjila", "gender": "M",
                                                       "parent": dad, "membership_category": "LM"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        kid = r.data["id"]
        self.assertNotEqual(r.data["membership_number"], None)

        # a second new branch must not see the first one's people, and numbers stay unique
        other = self.c.post("/api/admin/branches", {"name": "Thekkekara"}, format="json").data["slug"]
        r = self.c.post(f"/api/admin/members/{other}", {"first_name": "Rosa", "last_name": "T", "gender": "F",
                                                        "membership_category": "LM"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.c.get(f"/api/admin/members/{other}/{dad}").status_code, 404)

        r = self.c.get(f"/api/tree/{slug}")
        self.assertEqual(len(r.data["roots"]), 1)
        self.assertEqual(r.data["roots"][0]["children"][0]["first_name"], "Ethan")
        r = self.c.get("/api/branches")
        row = next(b for b in r.data["branches"] if b["slug"] == slug)
        self.assertEqual(row["members"], 2)
        r = self.c.get("/api/members", {"q": "Ethan"})
        self.assertEqual(r.data["count"], 1)

        # rename + hide
        r = self.c.patch(f"/api/admin/branches/{slug}", {"name": "Kunjila family", "hidden": True}, format="json")
        self.assertEqual(r.data["name"], "Kunjila family")
        self.assertNotIn(slug, [b["slug"] for b in self.c.get("/api/branches").data["branches"]])
        self.assertEqual(self.c.get(f"/api/admin/members/{slug}/{kid}").status_code, 200)  # still reachable

        # can't delete while people are in it
        self.assertEqual(self.c.delete(f"/api/admin/branches/{slug}").status_code, 400)
        self.c.delete(f"/api/admin/members/{slug}/{dad}?force=1")
        self.assertEqual(self.c.delete(f"/api/admin/branches/{slug}").status_code, 204)
        self.assertEqual(self.c.get(f"/api/tree/{slug}").status_code, 404)

    def test_branch_names_for_waiting_members(self):
        u = User.objects.create_user("waiting", password="x-Pass-123")
        c = APIClient()
        c.force_authenticate(u)
        r = c.get("/api/branch-names")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]["slug"], "aipu")
        self.assertEqual(APIClient().get("/api/branch-names").status_code, 401)

    def test_only_committee_can_manage(self):
        c = APIClient()
        self.assertIn(c.post("/api/admin/branches", {"name": "X"}, format="json").status_code, (401, 403))


class OtpDemoModeTests(TestCase):
    """OTP_DEMO sends the code back to the app (testing only); off by default."""

    def test_code_hidden_by_default(self):
        res = APIClient().post("/api/auth/otp/request", {"phone": "9000000101"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("demo_code", res.json())

    def test_demo_code_returned_and_works(self):
        from django.test import override_settings
        with override_settings(OTP_DEMO=True):
            c = APIClient()
            res = c.post("/api/auth/otp/request", {"phone": "9000000102"}, format="json")
            code = res.json()["demo_code"]
            self.assertRegex(code, r"^\d{6}$")
            ok = c.post("/api/auth/otp/verify", {"phone": "9000000102", "code": code}, format="json")
            self.assertEqual(ok.status_code, 200)
            self.assertIn("access", ok.json())


class FaceScanTests(TestCase):
    """Face scan sign in. The face engine is swapped for a fake so these run without OpenCV."""

    def setUp(self):
        from django.core.cache import cache
        from api import face as face_mod
        cache.clear()
        self.face = face_mod
        self._embed = face_mod.embed
        # fake "photos": the text says whose face it is
        vec = {"me": [1.0] + [0.0] * 127, "me2": [0.95, 0.31] + [0.0] * 126, "other": [0.0, 1.0] + [0.0] * 126}

        def fake_embed(img):
            if img == "none":
                raise face_mod.FaceError("no_face", "We couldn't see a face.")
            return vec[img]
        face_mod.embed = fake_embed
        self.user = User.objects.create_user("faceuser", password="x")
        Profile.objects.create(user=self.user, full_name="Face User", phone_number="+919000000001", is_approved=True)
        self.c = APIClient()

    def tearDown(self):
        self.face.embed = self._embed

    def enroll(self, images=("me", "me2", "me"), consent=True):
        self.c.force_authenticate(self.user)
        r = self.c.post("/api/auth/face/enroll", {"images": list(images), "consent": consent, "device_name": "Test"}, format="json")
        self.c.force_authenticate(None)
        return r

    def test_enroll_then_login_goes_home(self):
        r = self.enroll()
        self.assertEqual(r.status_code, 201, r.data)
        key = r.data["device_key"]
        r = self.c.post("/api/auth/face/login", {"device_key": key, "image": "me2"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        self.assertTrue(r.data["me"]["face_enrolled"])
        self.assertNotIn("photo", str(FaceProfile.objects.get(user=self.user).embeddings)[:10])

    def test_consent_required_and_mismatched_photos(self):
        self.assertEqual(self.enroll(consent=False).data["code"], "consent")
        self.assertEqual(self.enroll(images=("me", "other")).data["code"], "mismatch")
        self.assertEqual(self.enroll(images=("me", "none")).data["code"], "no_face")
        self.assertFalse(FaceProfile.objects.exists())

    def test_wrong_face_wrong_phone_and_lockout(self):
        key = self.enroll().data["device_key"]
        r = self.c.post("/api/auth/face/login", {"device_key": "someone-elses-phone", "image": "me"}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (401, "unknown_device"))
        r = self.c.post("/api/auth/face/login", {"device_key": key, "image": "none"}, format="json")
        self.assertEqual(r.data["code"], "no_face")  # no face doesn't count as a try
        for i in range(4):
            r = self.c.post("/api/auth/face/login", {"device_key": key, "image": "other"}, format="json")
            self.assertEqual((r.status_code, r.data["tries_left"]), (401, 4 - i))
        r = self.c.post("/api/auth/face/login", {"device_key": key, "image": "other"}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (429, "locked"))
        r = self.c.post("/api/auth/face/login", {"device_key": key, "image": "me"}, format="json")
        self.assertEqual(r.status_code, 429)  # even the right face waits

    def test_setting_up_again_replaces_old_phone_and_delete_removes_all(self):
        old = self.enroll().data["device_key"]
        new = self.enroll().data["device_key"]
        self.assertEqual(self.c.post("/api/auth/face/login", {"device_key": old, "image": "me"}, format="json").status_code, 401)
        self.assertEqual(self.c.post("/api/auth/face/login", {"device_key": new, "image": "me"}, format="json").status_code, 200)
        self.c.force_authenticate(self.user)
        self.assertTrue(self.c.get("/api/auth/face").data["enrolled"])
        self.assertEqual(self.c.delete("/api/auth/face").status_code, 204)
        self.assertFalse(self.c.get("/api/auth/face").data["enrolled"])
        self.c.force_authenticate(None)
        self.assertEqual(self.c.post("/api/auth/face/login", {"device_key": new, "image": "me"}, format="json").status_code, 401)

    def test_declined_member_cannot_face_login(self):
        key = self.enroll().data["device_key"]
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.c.post("/api/auth/face/login", {"device_key": key, "image": "me"}, format="json").status_code, 403)


class FaceEngineTests(TestCase):
    """The real OpenCV models on real photos (runs only where OpenCV, the models and scikit-image are installed)."""

    def test_real_models(self):
        try:
            import cv2
            from skimage import data
        except ImportError:
            self.skipTest("OpenCV / scikit-image not installed")
        from api import face
        if not face.available():
            self.skipTest("face models missing")
        jpg = lambda im: cv2.imencode(".jpg", im)[1].tobytes()  # noqa: E731
        astro = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
        a = face.embed(jpg(astro))
        b = face.embed(jpg(cv2.convertScaleAbs(cv2.resize(astro[20:480, 40:470], (300, 320)), alpha=1.2, beta=10)))
        other = face.embed(jpg(cv2.cvtColor(data.camera()[20:300, 120:400], cv2.COLOR_GRAY2BGR)))  # cropped: his face is small
        self.assertGreater(face.similarity(a, b), 0.6)
        self.assertLess(face.similarity(a, other), 0.36)
        with self.assertRaises(face.FaceError):
            face.embed(jpg(cv2.cvtColor(data.coffee(), cv2.COLOR_RGB2BGR)))


class DashboardWeekTests(TestCase):
    def test_dashboard_has_seven_days(self):
        staff = User.objects.create_user("wk", password="x", is_staff=True)
        Profile.objects.create(user=staff, full_name="Week", phone_number="+919000000077", is_approved=True)
        c = APIClient()
        c.force_authenticate(staff)
        r = c.get("/api/admin/dashboard")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["week"]), 7)
        self.assertIn("birthdays", r.data["week"][0])
