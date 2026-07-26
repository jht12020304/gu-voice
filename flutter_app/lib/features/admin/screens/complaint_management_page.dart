import 'package:flutter/material.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../data/api/complaints_api.dart';
import '../../../data/models/session.dart';

// Port of ComplaintManagementPage.tsx: chief-complaint template admin.
// Loads all templates (activeOnly:false), client-side search, create/edit dialog
// (name / nameEn / category / description / displayOrder), soft-delete with confirm.
// Backend localizes name/category/description via Accept-Language, so refetch on
// language change (URL is the language authority).
class ComplaintManagementPage extends StatefulWidget {
  const ComplaintManagementPage({super.key});

  @override
  State<ComplaintManagementPage> createState() => _ComplaintManagementPageState();
}

class _ComplaintManagementPageState extends State<ComplaintManagementPage> {
  final _api = ComplaintsApi();

  List<Complaint> _complaints = [];
  bool _loading = true;
  String? _error;
  String _search = '';
  late String _lng;

  @override
  void initState() {
    super.initState();
    _lng = currentLng;
    Future.microtask(_load);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Refetch when the URL language changes so localized rows follow the UI.
    if (currentLng != _lng) {
      _lng = currentLng;
      _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = await _api.getComplaints(activeOnly: false);
      if (!mounted) return;
      setState(() {
        _complaints = list;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = t('admin.complaints.loadFailed');
        _loading = false;
      });
    }
  }

  List<Complaint> get _filtered {
    final kw = _search.trim().toLowerCase();
    if (kw.isEmpty) return _complaints;
    return _complaints.where((c) {
      return [c.name, c.nameEn, c.category, c.description]
          .whereType<String>()
          .any((v) => v.toLowerCase().contains(kw));
    }).toList();
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _openForm({Complaint? editing}) async {
    final saved = await showDialog<bool>(
      context: context,
      builder: (_) => _ComplaintFormDialog(
        api: _api,
        editing: editing,
        nextOrder: _complaints.length + 1,
      ),
    );
    if (saved == true) {
      _toast(t('admin.complaints.saveSuccess'));
      await _load();
    }
  }

  Future<void> _confirmDelete(Complaint c) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(t('admin.complaints.deleteTitle')),
        content: Text(t('admin.complaints.deleteConfirm', args: {'name': c.name})),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(t('admin.complaints.cancel'))),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(t('admin.complaints.confirmDelete')),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await _api.delete(c.id);
      _toast(t('admin.complaints.deleteSuccess'));
      await _load();
    } catch (_) {
      _toast(t('admin.complaints.deleteFailed'));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(t('admin.complaints.title'))),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openForm(),
        icon: const Icon(Icons.add),
        label: Text(t('admin.complaints.create')),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: Text(
              t('admin.complaints.subtitle'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: TextField(
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: t('admin.complaints.searchPlaceholder'),
              ),
              onChanged: (v) => setState(() => _search = v),
            ),
          ),
          Expanded(child: _body(context)),
        ],
      ),
    );
  }

  Widget _body(BuildContext context) {
    if (_loading && _complaints.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null && _complaints.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          const SizedBox(height: 8),
          FilledButton(onPressed: _load, child: Text(t('common.retry'))),
        ]),
      );
    }
    final rows = _filtered;
    if (rows.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(t('admin.complaints.emptyTitle'), style: Theme.of(context).textTheme.titleMedium),
          Text(t('admin.complaints.emptyMessage')),
        ]),
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: rows.length,
        itemBuilder: (_, i) => _card(context, rows[i]),
      ),
    );
  }

  Widget _card(BuildContext context, Complaint c) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        title: Text(c.name, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (c.nameEn != null && c.nameEn!.isNotEmpty) Text(c.nameEn!),
            const SizedBox(height: 4),
            Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.label_outline, size: 12),
                  const SizedBox(width: 4),
                  Text(c.category, style: Theme.of(context).textTheme.labelSmall),
                ]),
              ),
              Text('#${c.displayOrder}', style: Theme.of(context).textTheme.labelSmall),
            ]),
            if (c.description != null && c.description!.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(c.description!, style: Theme.of(context).textTheme.bodySmall),
            ],
          ],
        ),
        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
          IconButton(
            icon: const Icon(Icons.edit_outlined),
            tooltip: t('admin.complaints.edit'),
            onPressed: () => _openForm(editing: c),
          ),
          IconButton(
            icon: Icon(Icons.delete_outline, color: Theme.of(context).colorScheme.error),
            tooltip: t('admin.complaints.delete'),
            onPressed: () => _confirmDelete(c),
          ),
        ]),
      ),
    );
  }
}

class _ComplaintFormDialog extends StatefulWidget {
  const _ComplaintFormDialog({required this.api, required this.editing, required this.nextOrder});

  final ComplaintsApi api;
  final Complaint? editing;
  final int nextOrder;

  @override
  State<_ComplaintFormDialog> createState() => _ComplaintFormDialogState();
}

class _ComplaintFormDialogState extends State<_ComplaintFormDialog> {
  late final TextEditingController _name;
  late final TextEditingController _nameEn;
  late final TextEditingController _category;
  late final TextEditingController _description;
  late final TextEditingController _order;

  String? _error;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    final e = widget.editing;
    _name = TextEditingController(text: e?.name ?? '');
    _nameEn = TextEditingController(text: e?.nameEn ?? '');
    _category = TextEditingController(text: e?.category ?? '');
    _description = TextEditingController(text: e?.description ?? '');
    _order = TextEditingController(text: '${e?.displayOrder ?? widget.nextOrder}');
  }

  @override
  void dispose() {
    _name.dispose();
    _nameEn.dispose();
    _category.dispose();
    _description.dispose();
    _order.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _error = null);
    if (_name.text.trim().isEmpty || _category.text.trim().isEmpty) {
      setState(() => _error = t('admin.complaints.validationRequired'));
      return;
    }
    setState(() => _submitting = true);
    final nameEn = _nameEn.text.trim();
    final description = _description.text.trim();
    final payload = <String, dynamic>{
      'name': _name.text.trim(),
      if (nameEn.isNotEmpty) 'nameEn': nameEn,
      'category': _category.text.trim(),
      if (description.isNotEmpty) 'description': description,
      'displayOrder': int.tryParse(_order.text.trim()) ?? widget.nextOrder,
    };
    try {
      if (widget.editing != null) {
        await widget.api.update(widget.editing!.id, payload);
      } else {
        await widget.api.create({...payload, 'isActive': true});
      }
      if (mounted) Navigator.pop(context, true);
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = t('admin.complaints.saveFailed');
          _submitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final editing = widget.editing != null;
    return AlertDialog(
      title: Text(editing ? t('admin.complaints.editTitle') : t('admin.complaints.createTitle')),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
          TextField(
            controller: _name,
            decoration: InputDecoration(labelText: t('admin.complaints.fieldName')),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _nameEn,
            decoration: InputDecoration(labelText: t('admin.complaints.fieldNameEn')),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _category,
            decoration: InputDecoration(labelText: t('admin.complaints.fieldCategory')),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _description,
            minLines: 2,
            maxLines: 4,
            decoration: InputDecoration(labelText: t('admin.complaints.fieldDescription')),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _order,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(labelText: t('admin.complaints.fieldDisplayOrder')),
          ),
        ]),
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.pop(context, false),
          child: Text(t('admin.complaints.cancel')),
        ),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: Text(_submitting ? t('admin.complaints.saving') : t('admin.complaints.save')),
        ),
      ],
    );
  }
}
