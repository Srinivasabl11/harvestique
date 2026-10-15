import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../auth/auth_controller.dart';
import 'calendar_screen.dart';

const reminderTypes = [
  'crop_observation',
  'irrigation',
  'activity',
  'crop_health',
  'harvest',
  'buyer_opportunity',
  'collection',
  'expense',
  'custom',
];

IconData reminderIcon(String t) => switch (t) {
      'crop_observation' => Icons.visibility_outlined,
      'irrigation' => Icons.water_drop_outlined,
      'activity' => Icons.agriculture_outlined,
      'crop_health' => Icons.eco_outlined,
      'harvest' => Icons.grass,
      'buyer_opportunity' => Icons.storefront_outlined,
      'collection' => Icons.local_shipping_outlined,
      'expense' => Icons.receipt_outlined,
      _ => Icons.alarm,
    };

/// Checks a reminder before it is sent. Returns the first problem, or null.
String? validateReminder({required String title, required DateTime due, required DateTime now}) {
  if (title.trim().isEmpty) return 'Write what you want to be reminded about.';
  if (title.trim().length > 160) return 'Keep it shorter (160 characters at most).';
  if (due.isBefore(now.subtract(const Duration(minutes: 1)))) return 'That time has already passed. Choose a later time.';
  return null;
}

/// Shows a failure with a Retry action (used for every reminder change).
void showFailure(BuildContext context, Object error, Future<void> Function() retry) {
  final f = error is AppFailure ? error : mapDioError(error);
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Text(f.message),
        duration: const Duration(seconds: 6),
        action: SnackBarAction(label: 'Retry', onPressed: retry),
      ),
    );
}

/// Reminders (farmers and buyers), suggestions from recorded data (farmers), and the calendar.
class RemindersScreen extends ConsumerStatefulWidget {
  const RemindersScreen({super.key});

  @override
  ConsumerState<RemindersScreen> createState() => _RemindersScreenState();
}

class _RemindersScreenState extends ConsumerState<RemindersScreen> {
  Key _key = UniqueKey();
  final _busy = <String>{}; // reminders / suggestions with a request in flight: their buttons are disabled

  void _refresh() => setState(() => _key = UniqueKey());

  Future<Map<String, dynamic>> _load(ApiClient api, bool farmer) async {
    final pending = await api.getPage('/reminders', query: {'status': 'pending'});
    final suggestions = farmer ? await api.getList('/reminders/suggestions') : <Map<String, dynamic>>[];
    return {'pending': pending, 'suggestions': suggestions};
  }

  /// Runs one change for [id] at a time, shows the outcome and refreshes the list.
  Future<void> _act(String id, Future<void> Function() action, String success) async {
    if (_busy.contains(id)) return;
    setState(() => _busy.add(id));
    try {
      await action();
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(success)));
      _refresh();
    } catch (e) {
      if (mounted) showFailure(context, e, () => _act(id, action, success));
    } finally {
      if (mounted) setState(() => _busy.remove(id));
    }
  }

  Future<void> _edit([Map<String, dynamic>? reminder]) async {
    final saved = await showDialog<bool>(context: context, builder: (_) => ReminderDialog(reminder: reminder));
    if (saved == true && mounted) _refresh();
  }

  Future<void> _delete(Map<String, dynamic> r) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this reminder?'),
        content: Text('"${r.str('title')}" on ${dateTime(r.str('due_at'))}'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
        ],
      ),
    );
    if (sure != true || !mounted) return;
    await _act(r.str('id'), () => ref.read(apiProvider).delete('/reminders/${r.str('id')}'), 'Reminder deleted');
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    final farmer = ref.watch(authProvider).role == 'farmer';
    return Reloadable<Map<String, dynamic>>(
      key: _key,
      load: () => api.cached('reminders', () => _load(api, farmer), (j) => j is Map<String, dynamic> ? j : <String, dynamic>{}),
      builder: (context, d, reload) {
        final pending = d.objs('pending');
        final suggestions = d.objs('suggestions');
        return ListView(
          padding: const EdgeInsets.only(bottom: 96),
          children: [
            Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      icon: const Icon(Icons.add_alarm),
                      label: const Text('New reminder'),
                      onPressed: _edit,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.calendar_month),
                      label: const Text('Calendar'),
                      onPressed: () =>
                          Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const CalendarScreen())),
                    ),
                  ),
                ],
              ),
            ),
            if (suggestions.isNotEmpty)
              SectionCard(
                title: 'Suggested from your records',
                icon: Icons.lightbulb_outline,
                child: Column(
                  children: [
                    for (final (i, s) in suggestions.indexed)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(reminderIcon(s.str('reminder_type'))),
                        title: Text(s.str('title')),
                        subtitle: Text('${s.str('reason')}\n${dateTime(s.str('due_at'))}'),
                        isThreeLine: true,
                        trailing: TextButton(
                          onPressed: _busy.contains('suggestion-$i')
                              ? null
                              : () => _act(
                                    'suggestion-$i',
                                    () => api.post(
                                      '/reminders?from_suggestion=true',
                                      body: {
                                        for (final k in ['reminder_type', 'title', 'due_at', 'farm_id', 'crop_cycle_id'])
                                          if (s[k] != null) k: s[k],
                                      },
                                    ),
                                    'Reminder added',
                                  ),
                          child: const Text('Add'),
                        ),
                      ),
                  ],
                ),
              ),
            SectionCard(
              title: 'Pending reminders (${pending.length})',
              icon: Icons.alarm,
              child: pending.isEmpty
                  ? const Text('Nothing pending. Tap "New reminder" to add one.')
                  : Column(
                      children: [
                        for (final r in pending)
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: Icon(reminderIcon(r.str('reminder_type'))),
                            title: Text(r.str('title')),
                            subtitle: Text(
                              '${dateTime(r.str('due_at'))}${r.str('recurrence') == 'none' ? '' : ' · repeats ${r.str('recurrence')}'}'
                              '${r.str('notes').isEmpty ? '' : '\n${r.str('notes')}'}',
                            ),
                            trailing: _busy.contains(r.str('id'))
                                ? const SizedBox(
                                    width: 48,
                                    height: 48,
                                    child: Padding(padding: EdgeInsets.all(14), child: CircularProgressIndicator(strokeWidth: 2)),
                                  )
                                : Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      IconButton(
                                        tooltip: 'Mark done',
                                        icon: const Icon(Icons.check_circle_outline),
                                        onPressed: () => _act(
                                          r.str('id'),
                                          () => api.post('/reminders/${r.str('id')}/complete'),
                                          r.str('recurrence') == 'none' ? 'Marked done' : 'Done — moved to the next time',
                                        ),
                                      ),
                                      PopupMenuButton<String>(
                                        tooltip: 'More actions',
                                        onSelected: (v) => v == 'edit' ? _edit(r) : _delete(r),
                                        itemBuilder: (context) => const [
                                          PopupMenuItem(
                                            value: 'edit',
                                            child: ListTile(leading: Icon(Icons.edit_outlined), title: Text('Edit / reschedule')),
                                          ),
                                          PopupMenuItem(
                                            value: 'delete',
                                            child: ListTile(leading: Icon(Icons.delete_outline), title: Text('Delete')),
                                          ),
                                        ],
                                      ),
                                    ],
                                  ),
                          ),
                      ],
                    ),
            ),
          ],
        );
      },
    );
  }
}

/// New reminder, or edit / reschedule an existing one ([reminder]).
class ReminderDialog extends ConsumerStatefulWidget {
  const ReminderDialog({super.key, this.reminder});

  final Map<String, dynamic>? reminder;

  @override
  ConsumerState<ReminderDialog> createState() => _ReminderDialogState();
}

class _ReminderDialogState extends ConsumerState<ReminderDialog> {
  late final _title = TextEditingController(text: widget.reminder?.str('title') ?? '');
  late final _notes = TextEditingController(text: widget.reminder?.str('notes') ?? '');
  late String _type = widget.reminder?.str('reminder_type', 'custom') ?? 'custom';
  late String _recurrence = widget.reminder?.str('recurrence', 'none') ?? 'none';
  late DateTime _when;
  late TimeOfDay _time;
  bool _saving = false;
  String? _error;

  bool get _editing => widget.reminder != null;

  @override
  void initState() {
    super.initState();
    final existing = DateTime.tryParse(widget.reminder?.str('due_at') ?? '')?.toLocal();
    final start = existing ?? DateTime.now().add(const Duration(days: 1));
    _when = DateTime(start.year, start.month, start.day);
    _time = existing == null ? const TimeOfDay(hour: 7, minute: 0) : TimeOfDay(hour: start.hour, minute: start.minute);
  }

  @override
  void dispose() {
    _title.dispose();
    _notes.dispose();
    super.dispose();
  }

  DateTime get _due => DateTime(_when.year, _when.month, _when.day, _time.hour, _time.minute);

  Future<void> _save() async {
    if (_saving) return; // one tap, one reminder
    final problem = validateReminder(title: _title.text, due: _due, now: DateTime.now());
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final body = <String, dynamic>{
      'reminder_type': _type,
      'title': _title.text.trim(),
      'due_at': isoWithOffset(_due),
      'recurrence': _recurrence,
      'notes': _notes.text.trim().isEmpty ? null : _notes.text.trim(),
    };
    try {
      final api = ref.read(apiProvider);
      if (_editing) {
        await api.patch('/reminders/${widget.reminder!.str('id')}', body);
      } else {
        body.removeWhere((k, v) => v == null);
        await api.post('/reminders', body: body);
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(_editing ? 'Reminder updated' : 'Reminder added')));
      Navigator.pop(context, true);
    } catch (e) {
      final f = e is AppFailure ? e : mapDioError(e);
      if (mounted) {
        setState(() {
          _error = f.message;
          _saving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(_editing ? 'Edit reminder' : 'New reminder'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
            TextField(
              controller: _title,
              maxLength: 160,
              decoration: const InputDecoration(labelText: 'What to do'),
              onChanged: (_) {
                if (_error != null) setState(() => _error = null);
              },
            ),
            DropdownButtonFormField<String>(
              initialValue: reminderTypes.contains(_type) ? _type : 'custom',
              decoration: const InputDecoration(labelText: 'Type'),
              items: [for (final t in reminderTypes) DropdownMenuItem(value: t, child: Text(label(t)))],
              onChanged: (v) => setState(() => _type = v ?? 'custom'),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Date'),
              subtitle: Text(day(isoDate(_when))),
              trailing: const Icon(Icons.edit_calendar),
              onTap: () async {
                final today = DateTime.now();
                final d = await showDatePicker(
                  context: context,
                  initialDate: _when.isBefore(DateTime(today.year, today.month, today.day)) ? today : _when,
                  firstDate: DateTime(today.year, today.month, today.day),
                  lastDate: DateTime(today.year + 5),
                );
                if (d != null) setState(() => _when = d);
              },
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Time'),
              subtitle: Text(_time.format(context)),
              trailing: const Icon(Icons.schedule),
              onTap: () async {
                final t = await showTimePicker(context: context, initialTime: _time);
                if (t != null) setState(() => _time = t);
              },
            ),
            DropdownButtonFormField<String>(
              initialValue: _recurrence,
              decoration: const InputDecoration(labelText: 'Repeat'),
              items: const [
                DropdownMenuItem(value: 'none', child: Text('Once')),
                DropdownMenuItem(value: 'daily', child: Text('Every day')),
                DropdownMenuItem(value: 'weekly', child: Text('Every week')),
              ],
              onChanged: (v) => setState(() => _recurrence = v ?? 'none'),
            ),
            TextField(controller: _notes, maxLines: 2, decoration: const InputDecoration(labelText: 'Notes (optional)')),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: _saving ? null : () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton(
          onPressed: _saving ? null : _save,
          child: Text(_saving ? 'Saving…' : 'Save'),
        ),
      ],
    );
  }
}
