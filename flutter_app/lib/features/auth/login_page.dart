import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config/env.dart';
import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../core/theme/app_tokens.dart';
import '../../shared/widgets/language_bar.dart';
import 'auth_notifier.dart';

// 2026-08-22 重設計，依 .claude/skills/design-taste-frontend（taste-skill）。
//
// Design read：醫療機構雙情境登入（kiosk 病患＋醫師個人裝置），trust-first 受監管
// 情境 → 沿用既有 token 系統（品牌藍為唯一 accent；skill 對受監管情境明文允許
// Inter/中性字體），calm-clinical 極簡。這一版修掉的 skill 硬規則違規：
//   §4.6  label 一律在輸入框上方，不得用 placeholder 當 label
//   §4.5  完整互動狀態：loading 保持版面形狀、:active 按壓回饋（scale .98）、
//         行內錯誤（不是 toast）
//   §4.4  圓角統一一套（12）——原版 8/6/pill 混用
//   §4.2  單一 accent 鎖定（品牌藍），錯誤紅只用於錯誤語意
//   §4.7  疊層紀律：標誌區塊（一個）→ 表單 → 輔助動作，不塞多餘小字
class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _passwordFocus = FocusNode();
  String? _localError;
  bool _obscure = true;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _passwordFocus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final email = _email.text.trim();
    final password = _password.text;
    if (email.isEmpty) {
      setState(() => _localError = t('common.login.emailRequired'));
      return;
    }
    if (password.isEmpty) {
      setState(() => _localError = t('common.login.passwordRequired'));
      return;
    }
    setState(() => _localError = null);
    try {
      await ref.read(authProvider.notifier).login(email, password);
      // Router redirect navigates to the role home on success.
    } catch (_) {
      // error surfaced via authProvider.error below
    }
  }

  void _fill(String email, String password) {
    _email.text = email;
    _password.text = password;
    setState(() => _localError = null);
  }

  static const _radius = 12.0; // §4.4 shape lock：本頁唯一圓角

  InputDecoration _fieldDecoration(BuildContext context, {Widget? suffixIcon}) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    // 不帶 labelText / hintText：label 是欄位上方的獨立 Text（§4.6），
    // placeholder 不承載任何必要資訊。
    return InputDecoration(
      isDense: false,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      suffixIcon: suffixIcon,
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(_radius),
        borderSide: BorderSide(color: tk.edge),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(_radius),
        borderSide: BorderSide(color: tk.edgeFocus, width: 2),
      ),
    );
  }

  Widget _fieldLabel(BuildContext context, String text) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(
          text,
          style: Theme.of(context).textTheme.labelLarge?.copyWith(
                fontWeight: FontWeight.w600,
                color: Theme.of(context).extension<AppTokens>()!.inkBody,
              ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final error = _localError ?? auth.error;
    final theme = Theme.of(context);
    final tk = theme.extension<AppTokens>()!;

    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: AutofillGroup(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // ── 標誌區塊（§4.7：一個，不疊）。外層 Column 是 stretch，
                  //    必須用 Align 收回固定尺寸，否則章被拉成整條橫幅。──────
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Container(
                      width: 56,
                      height: 56,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: theme.colorScheme.primary.withValues(alpha: .10),
                        borderRadius: BorderRadius.circular(_radius + 4),
                      ),
                      child: Icon(Icons.health_and_safety_outlined,
                          size: 30, color: theme.colorScheme.primary),
                    ),
                  ),
                  const SizedBox(height: 20),
                  Text(
                    t('common.appTitle'),
                    style: theme.textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      letterSpacing: -0.5,
                      color: tk.inkHeading,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    t('common.login.prompt'),
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(color: tk.inkSecondary),
                  ),
                  const SizedBox(height: 32),

                  // ── 表單（§4.6：label 在上、錯誤在下、行內）──────────
                  _fieldLabel(context, t('common.login.emailLabel')),
                  TextField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.email],
                    textInputAction: TextInputAction.next,
                    onSubmitted: (_) => _passwordFocus.requestFocus(),
                    decoration: _fieldDecoration(context),
                  ),
                  const SizedBox(height: 20),
                  _fieldLabel(context, t('common.login.passwordLabel')),
                  TextField(
                    controller: _password,
                    focusNode: _passwordFocus,
                    obscureText: _obscure,
                    autofillHints: const [AutofillHints.password],
                    onSubmitted: (_) => _submit(),
                    decoration: _fieldDecoration(
                      context,
                      suffixIcon: IconButton(
                        icon: Icon(
                          _obscure
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined,
                          size: 20,
                          color: tk.inkMuted,
                        ),
                        onPressed: () => setState(() => _obscure = !_obscure),
                      ),
                    ),
                  ),
                  if (error != null) ...[
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 14, vertical: 10),
                      decoration: BoxDecoration(
                        color: tk.alertCriticalBg,
                        borderRadius: BorderRadius.circular(_radius),
                      ),
                      child: Row(children: [
                        Icon(Icons.error_outline,
                            size: 18, color: tk.alertCritical),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(error,
                              style: TextStyle(
                                  color: tk.alertCritical, fontSize: 13.5)),
                        ),
                      ]),
                    ),
                  ],
                  const SizedBox(height: 24),

                  // ── 主 CTA（§4.5：loading 保形、按壓回饋；56pt 高 = kiosk 觸控）─
                  _PressableScale(
                    child: FilledButton(
                      onPressed: auth.isLoading ? null : _submit,
                      style: FilledButton.styleFrom(
                        minimumSize: const Size.fromHeight(56),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(_radius),
                        ),
                        textStyle: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w600),
                      ),
                      child: auth.isLoading
                          ? const SizedBox(
                              height: 22,
                              width: 22,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2.5, color: Colors.white),
                            )
                          : Text(t('common.login.submit')),
                    ),
                  ),

                  // ── 測試帶入（僅測試建置存在；§4.5 CTA 意圖不重複：
                  //    「帶入」是填表意圖，與「登入」CTA 分離）──────────
                  if (Env.hasE2eCredentials || Env.hasE2eDoctorCredentials) ...[
                    const SizedBox(height: 20),
                    Row(children: [
                      Expanded(child: Divider(color: tk.edge)),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        child: Text(
                          '測試帳號',
                          style: theme.textTheme.labelSmall
                              ?.copyWith(color: tk.inkMuted),
                        ),
                      ),
                      Expanded(child: Divider(color: tk.edge)),
                    ]),
                    const SizedBox(height: 12),
                    Row(children: [
                      if (Env.hasE2eDoctorCredentials)
                        Expanded(
                          child: _TestFillButton(
                            key: const Key('fill-doctor-credentials'),
                            icon: Icons.medical_services_outlined,
                            label: '帶入醫師帳號',
                            enabled: !auth.isLoading,
                            onTap: () => _fill(
                                Env.e2eDoctorEmail, Env.e2eDoctorPassword),
                          ),
                        ),
                      if (Env.hasE2eCredentials &&
                          Env.hasE2eDoctorCredentials)
                        const SizedBox(width: 12),
                      if (Env.hasE2eCredentials)
                        Expanded(
                          child: _TestFillButton(
                            key: const Key('fill-e2e-credentials'),
                            icon: Icons.person_outline,
                            label: '帶入病患帳號',
                            enabled: !auth.isLoading,
                            onTap: () => _fill(Env.e2eEmail, Env.e2ePassword),
                          ),
                        ),
                    ]),
                  ],

                  const SizedBox(height: 16),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      TextButton(
                        onPressed: () => context.go(
                          prefixLngToPath('/forgot-password', currentLng),
                        ),
                        child: Text(t('common.login.forgotPassword')),
                      ),
                      TextButton(
                        onPressed: () => context
                            .go(prefixLngToPath('/register', currentLng)),
                        child: Text(t('auth.register.title')),
                      ),
                    ],
                  ),
                  const SizedBox(height: 28),
                  const LanguageBar(),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// §4.5 tactile feedback：按下時 scale .98。包在按鈕外層、只作用於視覺，
/// 不攔截手勢（Listener 不吃事件）。
class _PressableScale extends StatefulWidget {
  const _PressableScale({required this.child});
  final Widget child;

  @override
  State<_PressableScale> createState() => _PressableScaleState();
}

class _PressableScaleState extends State<_PressableScale> {
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    return Listener(
      onPointerDown: (_) => setState(() => _down = true),
      onPointerUp: (_) => setState(() => _down = false),
      onPointerCancel: (_) => setState(() => _down = false),
      child: AnimatedScale(
        scale: _down ? 0.98 : 1.0,
        duration: const Duration(milliseconds: 90),
        child: widget.child,
      ),
    );
  }
}

/// 測試帶入鈕：次要視覺（tonal、低飽和），不與主 CTA 搶層級（§4.2 單一 accent）。
class _TestFillButton extends StatelessWidget {
  const _TestFillButton({
    super.key,
    required this.icon,
    required this.label,
    required this.enabled,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return _PressableScale(
      child: OutlinedButton.icon(
        onPressed: enabled ? onTap : null,
        icon: Icon(icon, size: 18),
        label: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(48),
          side: BorderSide(color: tk.edge),
          foregroundColor: tk.inkBody,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle:
              const TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
        ),
      ),
    );
  }
}
