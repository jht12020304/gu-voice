import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config/env.dart';
import '../../core/i18n/loc.dart';
import '../../core/router/lng.dart';
import '../../core/theme/app_theme.dart';
import '../../core/theme/app_tokens.dart';
import '../../shared/widgets/language_action.dart' show LanguageMenuButton;
import 'auth_notifier.dart';

// 2026-08-22 重設計、2026-08-23 精簡（使用者拍板），依
// .claude/skills/design-taste-frontend（taste-skill）。
//
// Design read：醫療機構雙情境登入（kiosk 病患＋醫師個人裝置），trust-first 受監管
// 情境 → 沿用既有 token 系統（品牌藍為唯一 accent；skill 對受監管情境明文允許
// Inter/中性字體），calm-clinical 極簡。
//
// 2026-08-23 這一輪（使用者逐條指定）：
//   - 拿掉頂部標誌方塊——App 圖示已在主畫面與啟動畫面出現過，登入頁再放一次
//     是重複的品牌噪音（§4.7 疊層紀律：一個標誌區塊即可，這裡由標題承擔）
//   - 拿掉「忘記密碼」「建立新帳號」——路由仍公開可深連，只是登入頁不再擺入口
//     （院內情境：帳號由 admin 開，不走自助註冊）
//   - 語言從 5 顆晶片列改成下拉選單（沿用 LanguageAction 的 PopupMenu 呈現方式），
//     底部只剩一顆按鈕，不再有一整片跟主流程搶注意力的色塊
//   - 「開始語音問診」72pt → 56pt，與登入鈕同一組尺寸（§4.4 形狀一致鎖）
//   - 去掉白卡＋陰影＋漸層底，改為平底 + hairline 分隔（§4.4：卡片只在「層級真的
//     需要抬升」時用；這頁只有一欄內容，卡片是純裝飾）
// 保留的 skill 硬規則：§4.6 label 在輸入框上方、§4.5 完整互動狀態（loading 保形、
// 按壓 scale .98、行內錯誤）、§4.4 單一圓角 12、§4.2 單一 accent。
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

  /// Kiosk 進場（2026-08-23）：以 kiosk 專用 patient 帳號登入後直接進選症狀頁。
  /// 錯誤沿用下方既有的 error 卡（authProvider.error）。
  Future<void> _startKiosk() async {
    setState(() => _localError = null);
    try {
      await ref.read(authProvider.notifier).login(Env.kioskEmail, Env.kioskPassword);
      if (!mounted) return;
      if (ref.read(authProvider).user != null) {
        context.go(prefixLngToPath('/patient/start', currentLng));
      }
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
  static const _buttonHeight = 56.0; // 兩顆動作鈕同一尺寸（kiosk 觸控仍達標）

  InputDecoration _fieldDecoration(BuildContext context, {Widget? suffixIcon}) {
    // 本頁鎖淺色：直接取 light 常數。不能用 Theme.of(context)——helper 收到的是
    // Theme 包裹**外面**的 context，深色模式下會拿到深色 tokens（白 8% 邊線畫在
    // 白卡上＝輸入框隱形，2026-08-23 目視抓到）。
    const tk = AppTokens.light;
    // 不帶 labelText / hintText：label 是欄位上方的獨立 Text（§4.6），
    // placeholder 不承載任何必要資訊。
    return InputDecoration(
      isDense: false,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      suffixIcon: suffixIcon,
      filled: true,
      fillColor: Colors.white,
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
          // 同 _fieldDecoration：鎖 light 常數，不吃外層（可能是深色的）Theme。
          style: AppTheme.light.textTheme.labelLarge?.copyWith(
                fontWeight: FontWeight.w600,
                color: AppTokens.light.inkBody,
              ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final error = _localError ?? auth.error;
    // 登入頁**鎖淺色**（2026-08-23 使用者拍板）：候診區迎賓頁不跟系統深色模式——
    // 明亮診間裡深色登入頁像關機螢幕。整頁包 AppTheme.light，狀態列 icon 轉深。
    final theme = AppTheme.light;
    final tk = AppTokens.light;

    return Theme(
      data: theme,
      child: AnnotatedRegion<SystemUiOverlayStyle>(
        value: SystemUiOverlayStyle.dark,
        child: Scaffold(
          body: SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 400),
                  child: AutofillGroup(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        // ── 標題（迎賓構圖——走到 iPad 前第一眼是名字，不是圖示）──
                        Text(
                          t('common.appTitle'),
                          textAlign: TextAlign.center,
                          style: theme.textTheme.headlineSmall?.copyWith(
                            fontWeight: FontWeight.w700,
                            letterSpacing: -0.5,
                            color: tk.inkHeading,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          t('common.login.prompt'),
                          textAlign: TextAlign.center,
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(color: tk.inkSecondary),
                        ),
                        const SizedBox(height: 36),

                        // ── Kiosk 進場（產品功能；未帶 KIOSK define 時整段死碼）────
                        //    候診 iPad 的主要動作：按下＝kiosk 帳號登入→直進選症狀。
                        //    放在表單之上——對走到 iPad 前的病患，這顆就是整頁的目的。
                        if (Env.hasKioskCredentials) ...[
                          _PressableScale(
                            child: FilledButton.icon(
                              onPressed: auth.isLoading ? null : _startKiosk,
                              style: FilledButton.styleFrom(
                                minimumSize:
                                    const Size.fromHeight(_buttonHeight),
                                shape: RoundedRectangleBorder(
                                    borderRadius:
                                        BorderRadius.circular(_radius)),
                                textStyle: const TextStyle(
                                    fontSize: 16, fontWeight: FontWeight.w600),
                              ),
                              icon: const Icon(Icons.mic, size: 20),
                              label: Text(t('common.login.kioskStart')),
                            ),
                          ),
                          const SizedBox(height: 28),
                          Divider(color: tk.edge, height: 1),
                          const SizedBox(height: 28),
                        ],

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
                              onPressed: () =>
                                  setState(() => _obscure = !_obscure),
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
                                        color: tk.alertCritical,
                                        fontSize: 13.5)),
                              ),
                            ]),
                          ),
                        ],
                        const SizedBox(height: 24),

                        // ── 登入 CTA（§4.5：loading 保形、按壓回饋）──────────
                        //    kiosk 鈕在場時這顆走描邊：整頁只留一塊實心藍
                        //    （§4.2 單一 accent 不等於兩顆一樣重的實心鈕——病患走
                        //    kiosk、醫師走登入，實心的那顆才是這台 iPad 的主動作）。
                        //    沒有 kiosk 鈕的建置（正式版）它就是唯一 CTA，回實心。
                        _PressableScale(
                          child: Env.hasKioskCredentials
                              ? OutlinedButton(
                                  key: const Key('login-submit'),
                                  onPressed: auth.isLoading ? null : _submit,
                                  style: OutlinedButton.styleFrom(
                                    minimumSize:
                                        const Size.fromHeight(_buttonHeight),
                                    foregroundColor: theme.colorScheme.primary,
                                    side: BorderSide(
                                        color: theme.colorScheme.primary
                                            .withValues(alpha: .45)),
                                    shape: RoundedRectangleBorder(
                                      borderRadius:
                                          BorderRadius.circular(_radius),
                                    ),
                                    textStyle: const TextStyle(
                                        fontSize: 16,
                                        fontWeight: FontWeight.w600),
                                  ),
                                  child: auth.isLoading
                                      ? SizedBox(
                                          height: 22,
                                          width: 22,
                                          child: CircularProgressIndicator(
                                              strokeWidth: 2.5,
                                              color:
                                                  theme.colorScheme.primary),
                                        )
                                      : Text(t('common.login.submit')),
                                )
                              : FilledButton(
                                  key: const Key('login-submit'),
                                  onPressed: auth.isLoading ? null : _submit,
                                  style: FilledButton.styleFrom(
                                    minimumSize:
                                        const Size.fromHeight(_buttonHeight),
                                    shape: RoundedRectangleBorder(
                                      borderRadius:
                                          BorderRadius.circular(_radius),
                                    ),
                                    textStyle: const TextStyle(
                                        fontSize: 16,
                                        fontWeight: FontWeight.w600),
                                  ),
                                  child: auth.isLoading
                                      ? const SizedBox(
                                          height: 22,
                                          width: 22,
                                          child: CircularProgressIndicator(
                                              strokeWidth: 2.5,
                                              color: Colors.white),
                                        )
                                      : Text(t('common.login.submit')),
                                ),
                        ),

                        // ── 測試帶入（僅測試建置存在；§4.5 CTA 意圖不重複：
                        //    「帶入」是填表意圖，與「登入」CTA 分離）──────────
                        if (Env.hasE2eCredentials ||
                            Env.hasE2eDoctorCredentials) ...[
                          const SizedBox(height: 20),
                          Row(children: [
                            Expanded(child: Divider(color: tk.edge)),
                            Padding(
                              padding:
                                  const EdgeInsets.symmetric(horizontal: 12),
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
                                  onTap: () => _fill(Env.e2eDoctorEmail,
                                      Env.e2eDoctorPassword),
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
                                  onTap: () =>
                                      _fill(Env.e2eEmail, Env.e2ePassword),
                                ),
                              ),
                          ]),
                        ],

                        // ── 語言：下拉（沿用 LanguageAction 的 PopupMenu 呈現）──
                        //    收成一顆按鈕，不再是五顆晶片的色塊。
                        const SizedBox(height: 32),
                        const Center(child: LanguageMenuButton()),
                      ],
                    ),
                  ),
                ),
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
