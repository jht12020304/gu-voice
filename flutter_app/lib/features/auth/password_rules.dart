import '../../core/i18n/loc.dart';

// Registration/reset password validation matching auth.password.* (RegisterPage.tsx /
// ResetPasswordPage.tsx): required, minLength 8, uppercase, lowercase, digit, confirm match.
// Returns a localized error string or null when valid.
String? validatePassword(String password, String confirm) {
  if (password.isEmpty) return t('auth.password.required');
  if (password.length < 8) return t('auth.password.minLength');
  if (!password.contains(RegExp(r'[A-Z]'))) return t('auth.password.needUppercase');
  if (!password.contains(RegExp(r'[a-z]'))) return t('auth.password.needLowercase');
  if (!password.contains(RegExp(r'[0-9]'))) return t('auth.password.needDigit');
  if (confirm.isEmpty) return t('auth.password.confirmRequired');
  if (password != confirm) return t('auth.password.confirmMismatch');
  return null;
}

final _emailRe = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

String? validateRegistration({
  required String name,
  required String email,
  required String password,
  required String confirm,
}) {
  if (name.trim().isEmpty) return t('auth.password.required');
  if (email.trim().isEmpty) return t('auth.email.required');
  if (!_emailRe.hasMatch(email.trim())) return t('auth.email.invalid');
  return validatePassword(password, confirm);
}
