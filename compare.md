# Native iOS declutter screenshots

The after images come from `ClinicalFlowTests` on an iPad (A16) simulator running iPadOS 26.5. The before images are earlier iPhone 17 Pro captures. Both sets use synthetic data.

| Screen | Before | After |
|---|---|---|
| Doctor’s SOAP report list | [Report list after upgrade](ios_native/Screenshots/02-native-after-upgrade.png) | [Doctor’s report list](artifacts/declutter-after/doctor-reports.png) |
| System administrator | [Administrator landing placeholder](ios_native/Screenshots/07-native-admin.png) | [User Management](artifacts/declutter-after/admin-users.png) |
| Report detail | [Report and red flag](ios_native/Screenshots/03-native-report.png) · [SOAP sections](ios_native/Screenshots/04-native-soap.png) | [Report detail](artifacts/declutter-after/report-detail.png) |
| Report detail with More open | [Report detail before the menu](ios_native/Screenshots/03-native-report.png) | [Export PDF, Quick orders, and Request Revision](artifacts/declutter-after/report-detail-more.png) |

The administrator pair compares the original placeholder with the current management screen. The older screenshot set predates the More menu.

## Verification

On an iPadOS 27 simulator, VoiceOver announced Export PDF, Quick orders, and Request Revision as buttons. Double-tapping the Request Revision button with VoiceOver enabled opened the reason form.

The iPad report dialog presents three visible actions. The XCTest hierarchy contains two nested button entries with the same identifier and frame for each action. The test now selects the first matching button by identifier and checks that it can be tapped. It opens the revision form, checks that empty and whitespace-only reasons disable submission, enters a reason, then cancels to keep the fixture reusable. The test checks that Export PDF is tappable, then opens Quick orders and checks its title. The administrator test opens Actions and finds Edit.

The iPadOS 26.5 run passed both clinical tests, both kiosk tests, and all 59 unit tests. The kiosk completion test also toggled the voice mute setting and changed the speech rate. The two clinical tests passed on iPadOS 27 as well.

The 26.5 simulator runs use the isolated `gu-voice-menu-a11y` Compose project. Set `COMPOSE_PROJECT_NAME` when running `ios_native/UITests/fixtures/seed-clinical.py` against that project. Set `TEST_RUNNER_CLINICAL_UI_TEST=1` for the clinical tests and `TEST_RUNNER_KIOSK_UI_TEST=1` for the kiosk tests.
