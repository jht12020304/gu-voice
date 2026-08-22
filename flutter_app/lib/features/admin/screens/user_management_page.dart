import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;

import '../../../core/i18n/loc.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/admin_api.dart';
import '../../../data/models/user.dart';
import '../../../shared/widgets/ui_kit.dart';
import '../../../shared/widgets/dashboard_back_button.dart';

// Port of frontend/src/screens/admin/UserManagementPage.tsx: admin user list with
// search + role/active filter + cursor infinite scroll, create/edit dialog, and a
// per-row active toggle. ponytail: web table rendered as cards (mobile-first idiom,
// matches PatientListPage); lastLoginAt column dropped because the Flutter User model
// doesn't carry it.
class UserManagementPage extends StatefulWidget {
  const UserManagementPage({super.key});

  @override
  State<UserManagementPage> createState() => _UserManagementPageState();
}

class _UserManagementPageState extends State<UserManagementPage> {
  final _api = AdminApi();
  final _scroll = ScrollController();
  Timer? _debounce;

  List<User> _users = [];
  String? _cursor;
  bool _hasMore = true;
  bool _loading = true;
  int _totalCount = 0;
  String _search = '';
  String? _role; // null = all
  bool? _active; // null = all, true = active, false = inactive
  String? _togglingId;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 300) _fetchMore();
    });
    Future.microtask(() => _fetch(reset: true));
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _fetch({required bool reset}) async {
    setState(() => _loading = true);
    try {
      final page = await _api.getUsers(
        cursor: reset ? null : _cursor,
        limit: 50,
        role: _role,
        isActive: _active,
        search: _search.trim().isEmpty ? null : _search.trim(),
      );
      if (!mounted) return;
      setState(() {
        _users = reset ? page.data : [..._users, ...page.data];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _totalCount = page.totalCount;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _fetchMore() async {
    if (!_hasMore || _loading || _cursor == null) return;
    await _fetch(reset: false);
  }

  void _onSearch(String q) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      setState(() => _search = q);
      _fetch(reset: true);
    });
  }

  void _setRole(String? role) {
    setState(() => _role = role);
    _fetch(reset: true);
  }

  void _setActive(bool? active) {
    setState(() => _active = active);
    _fetch(reset: true);
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _openForm({User? user}) async {
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _UserFormDialog(user: user),
    );
    if (result == null) return;
    try {
      if (user != null) {
        await _api.updateUser(user.id, result);
        _toast(t('admin.users.updateSuccess'));
      } else {
        await _api.createUser(result);
        _toast(t('admin.users.createSuccess'));
      }
      await _fetch(reset: true);
    } catch (_) {
      _toast(t('admin.users.operationFailed'));
    }
  }

  String? _resettingId;
  // 一次性臨時密碼；null = 不顯示。刻意只存在記憶體中。
  ({String email, String password})? _tempPassword;

  Future<void> _resetPassword(User user) async {
    if (_resettingId != null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(t('admin.users.resetPassword')),
        content: Text(t('admin.users.resetPasswordConfirm', args: {'email': user.email})),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(t('admin.users.cancel'))),
          FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text(t('admin.users.resetPassword'))),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _resettingId = user.id);
    try {
      final r = await _api.resetUserPassword(user.id);
      if (!mounted) return;
      setState(() => _tempPassword = (email: r.email, password: r.tempPassword));
      await _showTempPasswordDialog();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(t('admin.users.resetPasswordFailed'))));
      }
    } finally {
      if (mounted) setState(() => _resettingId = null);
    }
  }

  /// 一次性臨時密碼——關掉就拿不回來（後端只存 hash），所以警告要講清楚。
  Future<void> _showTempPasswordDialog() async {
    final info = _tempPassword;
    if (info == null) return;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        title: Text(t('admin.users.tempPasswordTitle')),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t('admin.users.tempPasswordFor', args: {'email': info.email})),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: SelectableText(
                info.password,
                style: Theme.of(ctx).textTheme.titleLarge?.copyWith(
                      fontFamily: 'monospace',
                      letterSpacing: 1.5,
                    ),
              ),
            ),
            TextButton(
              onPressed: () {
                Clipboard.setData(ClipboardData(text: info.password));
                ScaffoldMessenger.of(ctx).showSnackBar(
                    SnackBar(content: Text(t('admin.users.tempPasswordCopied'))));
              },
              child: Text(t('admin.users.tempPasswordCopy')),
            ),
          ]),
          const SizedBox(height: 12),
          Text(t('admin.users.tempPasswordWarning'),
              style: Theme.of(ctx).textTheme.bodySmall),
        ]),
        actions: [
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: Text(t('admin.users.tempPasswordDone')),
          ),
        ],
      ),
    );
    if (mounted) setState(() => _tempPassword = null);
  }

  Future<void> _toggleActive(User user) async {
    if (_togglingId != null) return;
    setState(() => _togglingId = user.id);
    try {
      await _api.toggleUserActive(user.id);
      _toast(user.isActive ? t('admin.users.deactivateSuccess') : t('admin.users.activateSuccess'));
      await _fetch(reset: true);
    } catch (_) {
      _toast(t('admin.users.toggleFailed'));
    } finally {
      if (mounted) setState(() => _togglingId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: const DashboardBackButton(),
        title: Text(t('admin.users.title')),
        actions: [
          IconButton(
            icon: const Icon(Icons.person_add_alt),
            tooltip: t('admin.users.create'),
            onPressed: () => _openForm(),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: TextField(
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: t('admin.users.searchPlaceholder'),
              ),
              onChanged: _onSearch,
            ),
          ),
          _filters(context),
          Expanded(child: _body(context)),
        ],
      ),
    );
  }

  Widget _filters(BuildContext context) {
    Widget roleChip(String? key, String label) => Padding(
          padding: const EdgeInsets.only(right: 8),
          child: ChoiceChip(
            label: Text(label),
            selected: _role == key,
            onSelected: (_) => _setRole(key),
          ),
        );
    Widget activeChip(bool? key, String label) => Padding(
          padding: const EdgeInsets.only(right: 8),
          child: FilterChip(
            label: Text(label),
            selected: _active == key,
            onSelected: (_) => _setActive(key),
          ),
        );
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Row(children: [
        roleChip(null, t('admin.users.roleTab.all')),
        roleChip('patient', t('admin.users.roleTab.patient')),
        roleChip('doctor', t('admin.users.roleTab.doctor')),
        roleChip('admin', t('admin.users.roleTab.admin')),
        const SizedBox(width: 8),
        activeChip(true, t('admin.users.statusActive')),
        activeChip(false, t('admin.users.statusInactive')),
      ]),
    );
  }

  Widget _body(BuildContext context) {
    if (_loading && _users.isEmpty) return const SkeletonList();
    if (_users.isEmpty) {
      return EmptyState(
        icon: Icons.people_outline,
        title: t('admin.users.emptyTitle'),
        message: t('admin.users.emptyMessage'),
      );
    }
    return ListView(
      controller: _scroll,
      padding: const EdgeInsets.all(16),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text('${t('admin.users.title')} · $_totalCount',
              style: Theme.of(context).textTheme.bodySmall),
        ),
        for (final u in _users) _row(context, u),
        if (_loading && _users.isNotEmpty)
          const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator())),
        if (!_hasMore) Center(child: Padding(padding: const EdgeInsets.all(12), child: Text(t('common.pagination.allLoaded')))),
      ],
    );
  }

  Widget _row(BuildContext context, User u) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final toggling = _togglingId == u.id;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
        child: Row(children: [
          CircleAvatar(child: Text(u.name.isNotEmpty ? u.name.characters.first : '?')),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(u.name, style: const TextStyle(fontWeight: FontWeight.w600), overflow: TextOverflow.ellipsis),
              Text(u.email, style: Theme.of(context).textTheme.bodySmall, overflow: TextOverflow.ellipsis),
              const SizedBox(height: 4),
              Wrap(spacing: 6, children: [
                PillTag(_roleLabel(u.role), color: Theme.of(context).colorScheme.primary),
                PillTag(
                  u.isActive ? t('admin.users.statusActive') : t('admin.users.statusInactive'),
                  color: u.isActive ? tk.statusCompleted : tk.statusCancelled,
                ),
              ]),
            ]),
          ),
          IconButton(
            icon: const Icon(Icons.edit_outlined),
            tooltip: t('admin.users.edit'),
            onPressed: () => _openForm(user: u),
          ),
          _resettingId == u.id
              ? const Padding(
                  padding: EdgeInsets.all(12),
                  child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                )
              : IconButton(
                  icon: const Icon(Icons.password_outlined),
                  tooltip: t('admin.users.resetPassword'),
                  onPressed: () => _resetPassword(u),
                ),
          toggling
              ? const Padding(
                  padding: EdgeInsets.all(12),
                  child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                )
              : Switch(
                  value: u.isActive,
                  onChanged: (_) => _toggleActive(u),
                ),
        ]),
      ),
    );
  }

  String _roleLabel(String role) => switch (role) {
        'patient' => t('admin.users.role.patient'),
        'doctor' => t('admin.users.role.doctor'),
        'admin' => t('admin.users.role.admin'),
        _ => role,
      };
}

// Create/edit user dialog. Returns the payload Map on submit, or null on cancel.
// Password field appears only in create mode (matches the web dialog).
class _UserFormDialog extends StatefulWidget {
  final User? user;
  const _UserFormDialog({this.user});

  @override
  State<_UserFormDialog> createState() => _UserFormDialogState();
}

class _UserFormDialogState extends State<_UserFormDialog> {
  late final TextEditingController _name;
  late final TextEditingController _email;
  late final TextEditingController _phone;
  final _password = TextEditingController();
  late String _role;
  late bool _isActive;
  String? _error;

  bool get _editing => widget.user != null;

  @override
  void initState() {
    super.initState();
    final u = widget.user;
    _name = TextEditingController(text: u?.name ?? '');
    _email = TextEditingController(text: u?.email ?? '');
    _phone = TextEditingController(text: u?.phone ?? '');
    _role = u?.role ?? 'patient';
    _isActive = u?.isActive ?? true;
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _phone.dispose();
    _password.dispose();
    super.dispose();
  }

  void _submit() {
    final name = _name.text.trim();
    final email = _email.text.trim();
    if (name.isEmpty || email.isEmpty) {
      setState(() => _error = t('admin.users.validationNameEmail'));
      return;
    }
    if (!_editing && _password.text.isEmpty) {
      setState(() => _error = t('admin.users.validationPassword'));
      return;
    }
    final phone = _phone.text.trim();
    final payload = <String, dynamic>{
      'name': name,
      'email': email,
      'role': _role,
      'isActive': _isActive,
      if (phone.isNotEmpty) 'phone': phone,
      if (!_editing) 'password': _password.text,
    };
    Navigator.of(context).pop(payload);
  }

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return AlertDialog(
      title: Text(_editing ? t('admin.users.editTitle') : t('admin.users.createTitle')),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (_error != null)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: tk.alertCriticalBg, borderRadius: BorderRadius.circular(8)),
              child: Text(_error!, style: TextStyle(color: tk.alertCritical)),
            ),
          TextField(controller: _name, decoration: InputDecoration(labelText: t('admin.users.fieldName'))),
          const SizedBox(height: 12),
          TextField(
            controller: _email,
            keyboardType: TextInputType.emailAddress,
            decoration: InputDecoration(labelText: t('admin.users.fieldEmail')),
          ),
          if (!_editing) ...[
            const SizedBox(height: 12),
            TextField(
              controller: _password,
              obscureText: true,
              decoration: InputDecoration(labelText: t('admin.users.fieldPassword')),
            ),
          ],
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _role,
            decoration: InputDecoration(labelText: t('admin.users.fieldRole')),
            items: [
              DropdownMenuItem(value: 'patient', child: Text(t('admin.users.role.patient'))),
              DropdownMenuItem(value: 'doctor', child: Text(t('admin.users.role.doctor'))),
              DropdownMenuItem(value: 'admin', child: Text(t('admin.users.role.admin'))),
            ],
            onChanged: (v) => setState(() => _role = v ?? _role),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _phone,
            keyboardType: TextInputType.phone,
            decoration: InputDecoration(labelText: t('admin.users.fieldPhone'), hintText: '0912345678'),
          ),
          const SizedBox(height: 4),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(t('admin.users.fieldIsActive')),
            value: _isActive,
            onChanged: (v) => setState(() => _isActive = v),
          ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: Text(t('admin.users.cancel'))),
        FilledButton(
          onPressed: _submit,
          child: Text(_editing ? t('admin.users.update') : t('admin.users.createConfirm')),
        ),
      ],
    );
  }
}
