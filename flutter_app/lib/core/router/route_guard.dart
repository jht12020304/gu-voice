// 路由守衛的純函式版本：go_router 的 redirect 只負責 lng 前綴與 booted 判斷，
// 「登入 / 角色 / 平台」三層規則全部集中在這裡，測試才能不啟動整個 App 就驗到。
//
// 平台分工（產品拍板）：
//   Web    → 病患語音問診 kiosk（現場候診機），醫師端也照舊可用
//   原生 iOS → 醫師專用 App：只看報告與通知，不做語音問診
// 所以 iOS build 上：問診/病患端路由整片關閉（deep link 也擋），醫師 landing 改成通知頁，
// 病患帳號登入只會看到 patient-unsupported 提示頁（含登出）。

import 'package:flutter/foundation.dart';

/// 醫師專用平台＝原生 iOS build。
///
/// 用 `!kIsWeb` 而不是只看 `defaultTargetPlatform`：Flutter Web 跑在 iPad/iPhone Safari 上時
/// `defaultTargetPlatform` 同樣回 `TargetPlatform.iOS`，只看它會把「iPad 上的 kiosk 網頁」
/// 誤判成醫師 App，直接把現場病患鎖在提示頁。
///
/// 測試覆寫方式：`debugDefaultTargetPlatformOverride = TargetPlatform.iOS`（`flutter test`
/// 跑在 VM 上，`kIsWeb` 恆為 false）。純函式 [resolveGuardRedirect] 另外收 bool 參數，
/// 連 web 那一側也能在單元測試裡表達。
bool get isDoctorOnlyPlatform => !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;

/// 病患帳號在醫師專用 App 上的提示頁（去掉 lng 前綴後的路徑）。
const patientUnsupportedRest = '/patient-unsupported';

/// 問診相關路由＝病患首頁子樹 + 語音問診子樹。
///
/// 一律用「整段比對」而不是 `startsWith('/patient')`：
///   - `/patient-unsupported` 若被算進來，病患會被 redirect 回自己這一頁 → go_router 迴圈
///   - `/patients`、`/patients/:id` 是醫師端的病患清單，在醫師 App 上必須開著
bool isConsultationArea(String rest) =>
    rest == '/patient' ||
    rest.startsWith('/patient/') ||
    rest == '/conversation' ||
    rest.startsWith('/conversation/');

/// 登入後該落在哪一頁。醫師 App 以「通知」為首頁——醫師打開 App 是要看有沒有新報告/警示，
/// 不是看 dashboard 統計。
String landingPath({
  required String lng,
  required bool isPatient,
  required bool doctorOnlyPlatform,
}) {
  if (doctorOnlyPlatform) {
    return isPatient ? '/$lng$patientUnsupportedRest' : '/$lng/notifications';
  }
  return isPatient ? '/$lng/patient' : '/$lng/dashboard';
}

/// booted 之後的 redirect 決策。回傳 null＝放行。
///
/// [path] 是含 lng 前綴的完整路徑，[rest] 是去掉 lng 前綴後的路徑。
String? resolveGuardRedirect({
  required String path,
  required String lng,
  required String rest,
  required bool isAuthenticated,
  required bool isPatient,
  required bool isAdmin,
  required bool doctorOnlyPlatform,
}) {
  final landing = landingPath(lng: lng, isPatient: isPatient, doctorOnlyPlatform: doctorOnlyPlatform);
  final isPublic =
      rest == '/login' || rest.startsWith('/forgot-password') || rest.startsWith('/reset-password');

  if (!isAuthenticated) return isPublic ? null : '/$lng/login';
  if (rest == '/login') return landing;
  // Route off the generic role home onto the role-specific landing.
  if (path == '/$lng' || path == '/$lng/') return landing;

  // ---- 平台閘門（Web 與其他平台完全不進這一段）----
  if (doctorOnlyPlatform) {
    if (isPatient) {
      // 病患帳號在醫師 App 裡只有一頁可待：提示頁（含登出）。
      return rest == patientUnsupportedRest ? null : landing;
    }
    // 醫護：問診/病患端路由整片關閉，deep link 進來也一樣。提示頁不是給醫護看的。
    if (isConsultationArea(rest) || rest == patientUnsupportedRest) return landing;
  } else if (rest == patientUnsupportedRest) {
    // 提示頁是 iOS 專屬的；其他平台當作不存在，交回各自角色的 landing。
    return landing;
  }

  // ---- RoleGuard（既有行為，逐字保留）：病患只能待在病患/問診區；admin 頁需 admin ----
  final isPatientArea = rest.startsWith('/patient') || rest.startsWith('/conversation');
  final isAdminArea = rest.startsWith('/admin');
  if (isPatient && !isPatientArea) return landing; // patient blocked from doctor/admin
  if (isAdminArea && !isAdmin) return landing; // admin-only subtree
  return null;
}
