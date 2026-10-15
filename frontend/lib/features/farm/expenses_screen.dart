import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';

/// The server's expense categories (ExpenseCategory).
const expenseCategories = ['seed', 'fertilizer', 'pesticide', 'labour', 'irrigation', 'machinery', 'transport', 'other'];

IconData expenseIcon(String category) => switch (category) {
      'seed' => Icons.grass,
      'fertilizer' => Icons.science_outlined,
      'pesticide' => Icons.bug_report_outlined,
      'labour' => Icons.groups_outlined,
      'irrigation' => Icons.water_drop_outlined,
      'machinery' => Icons.agriculture_outlined,
      'transport' => Icons.local_shipping_outlined,
      _ => Icons.receipt_long_outlined,
    };

/// Checks the form before it is sent (the server applies the same rules). Returns the first problem, or null.
String? validateExpense({
  required String? category,
  required String amountText,
  required DateTime date,
  required DateTime today,
}) {
  if (category == null) return 'Choose what the money was spent on.';
  final text = amountText.trim();
  final amount = double.tryParse(text);
  if (amount == null || amount <= 0) return 'Enter the amount in rupees (more than 0).';
  final dot = text.indexOf('.');
  if (dot >= 0 && text.length - dot - 1 > 2) return 'Use at most 2 digits after the decimal point.';
  if (amount >= 10000000000) return 'That amount is too large.';
  if (DateTime(date.year, date.month, date.day).isAfter(DateTime(today.year, today.month, today.day))) {
    return 'The expense date cannot be in the future.';
  }
  return null;
}

/// The request body the API expects (POST /farms/{farm_id}/expenses).
Map<String, dynamic> expenseBody({
  required String category,
  required double amount,
  required DateTime date,
  String? cycleId,
  String? description,
}) =>
    {
      'category': category,
      'amount': amount,
      'expense_date': isoDate(date),
      if (cycleId != null) 'crop_cycle_id': cycleId,
      if (description != null && description.trim().isNotEmpty) 'description': description.trim(),
    };

double expenseTotal(List<Map<String, dynamic>> expenses) => expenses.fold<double>(0, (sum, e) => sum + e.numVal('amount'));

/// A farm's expenses, or one crop's when [cycleId] is given: total, list, add and delete.
class ExpensesScreen extends ConsumerStatefulWidget {
  const ExpensesScreen({super.key, required this.farmId, this.cycleId, this.title = 'Expenses'});

  final String farmId;
  final String? cycleId;
  final String title;

  @override
  ConsumerState<ExpensesScreen> createState() => _ExpensesScreenState();
}

class _ExpensesScreenState extends ConsumerState<ExpensesScreen> {
  Key _key = UniqueKey();

  void _refresh() => setState(() => _key = UniqueKey());

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final r = await Future.wait([
      api.getObj(
        '/farms/${widget.farmId}/expenses',
        query: {'limit': 100, if (widget.cycleId != null) 'crop_cycle_id': widget.cycleId},
      ),
      api.getPage('/farms/${widget.farmId}/crop-cycles'),
    ]);
    return {'page': r[0], 'cycles': r[1]};
  }

  Future<void> _add(List<Map<String, dynamic>> cycles, [Map<String, dynamic>? expense]) async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => AddExpenseScreen(farmId: widget.farmId, cycles: cycles, cycleId: widget.cycleId, expense: expense),
      ),
    );
    if (saved == true && mounted) _refresh();
  }

  Future<void> _delete(Map<String, dynamic> e) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this expense?'),
        content: Text('${rupees(e.numVal('amount'))} · ${label(e.str('category'))} on ${day(e.str('expense_date'))}'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
        ],
      ),
    );
    if (sure != true || !mounted) return;
    final ok =
        await runAction(context, () => ref.read(apiProvider).delete('/expenses/${e.str('id')}'), success: 'Expense deleted');
    if (ok && mounted) _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Reloadable<Map<String, dynamic>>(
        key: _key,
        load: () => api.cached(
          'expenses:${widget.farmId}:${widget.cycleId ?? 'all'}',
          () => _load(api),
          (j) => j is Map<String, dynamic> ? j : <String, dynamic>{},
        ),
        builder: (context, d, reload) {
          final page = d.obj('page');
          final items = page.objs('items');
          final cycles = d.objs('cycles');
          final names = {for (final c in cycles) c.str('id'): c.str('crop_name')};
          final more = page.intVal('total') > items.length;
          return ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              SectionCard(
                title: 'Total spent',
                icon: Icons.currency_rupee,
                action: FilledButton.icon(
                  onPressed: () => _add(cycles),
                  icon: const Icon(Icons.add),
                  label: const Text('Add expense'),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(rupees(expenseTotal(items)), style: Theme.of(context).textTheme.headlineSmall),
                    Text(
                      more
                          ? 'Total of the latest ${items.length} of ${page.intVal('total')} expenses.'
                          : '${items.length} ${items.length == 1 ? 'expense' : 'expenses'} recorded by you.',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              if (items.isEmpty)
                const EmptyPanel(
                  icon: Icons.receipt_long_outlined,
                  message: 'No expenses yet. Tap "Add expense" to record seed, fertilizer, labour and other costs.',
                ),
              for (final e in items)
                ListTile(
                  leading: Icon(expenseIcon(e.str('category'))),
                  title: Text('${rupees(e.numVal('amount'))} · ${label(e.str('category'))}'),
                  subtitle: Text(
                    [
                      day(e.str('expense_date')),
                      if (widget.cycleId == null)
                        e.strOrNull('crop_cycle_id') == null ? 'Whole farm' : names[e.str('crop_cycle_id')] ?? 'Crop',
                      if (e.str('description').isNotEmpty) e.str('description'),
                    ].join(' · '),
                  ),
                  onTap: () => _add(cycles, e),
                  trailing: IconButton(tooltip: 'Delete', icon: const Icon(Icons.delete_outline), onPressed: () => _delete(e)),
                ),
            ],
          );
        },
      ),
    );
  }
}

/// Record one expense. Full screen (like Add crop) so every choice and every server message is visible.
class AddExpenseScreen extends ConsumerStatefulWidget {
  const AddExpenseScreen({super.key, required this.farmId, required this.cycles, this.cycleId, this.expense});

  /// The expense being edited; null when adding.
  final Map<String, dynamic>? expense;

  final String farmId;
  final List<Map<String, dynamic>> cycles;
  final String? cycleId;

  @override
  ConsumerState<AddExpenseScreen> createState() => _AddExpenseScreenState();
}

class _AddExpenseScreenState extends ConsumerState<AddExpenseScreen> {
  final _amount = TextEditingController();
  final _note = TextEditingController();
  late String? _category = widget.expense?.strOrNull('category');
  late String? _cycleId = widget.expense == null ? widget.cycleId : widget.expense!.strOrNull('crop_cycle_id');
  late DateTime _date = DateTime.tryParse(widget.expense?.str('expense_date') ?? '') ?? _today();

  @override
  void initState() {
    super.initState();
    final e = widget.expense;
    if (e != null) {
      final a = e.numVal('amount');
      _amount.text = a == a.roundToDouble() ? a.toStringAsFixed(0) : a.toStringAsFixed(2);
      _note.text = e.str('description');
    }
  }

  String? _error;
  bool _saving = false;

  static DateTime _today() {
    final n = DateTime.now();
    return DateTime(n.year, n.month, n.day);
  }

  @override
  void dispose() {
    _amount.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _pickDate() async {
    final d = await showDatePicker(context: context, initialDate: _date, firstDate: DateTime(2020), lastDate: _today());
    if (d == null || !mounted) return;
    setState(() {
      _date = d;
      _error = null;
    });
  }

  Future<void> _save() async {
    final problem = validateExpense(category: _category, amountText: _amount.text, date: _date, today: _today());
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final amount = double.parse(_amount.text.trim());
      final body = expenseBody(category: _category!, amount: amount, date: _date, cycleId: _cycleId, description: _note.text);
      if (widget.expense == null) {
        await ref.read(apiProvider).post('/farms/${widget.farmId}/expenses', body: body);
      } else {
        await ref.read(apiProvider).patch('/expenses/${widget.expense!.str('id')}', {
          ...body,
          'crop_cycle_id': _cycleId, // null moves it to the whole farm
          'description': _note.text.trim().isEmpty ? null : _note.text.trim(),
        });
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(widget.expense == null ? 'Expense of ${rupees(amount)} saved' : 'Expense updated')),
      );
      Navigator.of(context).pop(true);
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
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(widget.expense == null ? 'Add expense' : 'Edit expense')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null)
            Card(
              color: scheme.errorContainer,
              child: ListTile(
                leading: Icon(Icons.error_outline, color: scheme.onErrorContainer),
                title: Text(_error!, style: TextStyle(color: scheme.onErrorContainer)),
              ),
            ),
          Text('1. Spent on', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final c in expenseCategories)
                ChoiceChip(
                  avatar: Icon(expenseIcon(c), size: 18),
                  label: Text(label(c)),
                  selected: _category == c,
                  onSelected: (_) => setState(() {
                    _category = c;
                    _error = null;
                  }),
                ),
            ],
          ),
          const Divider(height: 32),
          Text('2. Amount', style: Theme.of(context).textTheme.titleMedium),
          TextField(
            controller: _amount,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Amount (₹)', prefixText: '₹ '),
            onChanged: (_) {
              if (_error != null) setState(() => _error = null);
            },
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Date'),
            subtitle: Text(day(isoDate(_date))),
            trailing: const Icon(Icons.edit_calendar),
            onTap: _pickDate,
          ),
          const Divider(height: 32),
          Text('3. For which crop (optional)', style: Theme.of(context).textTheme.titleMedium),
          DropdownButtonFormField<String?>(
            initialValue: _cycleId,
            isExpanded: true,
            items: [
              const DropdownMenuItem<String?>(child: Text('Whole farm (not one crop)')),
              for (final c in widget.cycles)
                DropdownMenuItem<String?>(
                  value: c.str('id'),
                  child:
                      Text('${c.str('crop_name')} · ${label(c.str('status')).toLowerCase()} · sown ${day(c.str('sowing_date'))}'),
                ),
            ],
            onChanged: (v) => setState(() => _cycleId = v),
          ),
          const SizedBox(height: 16), // keeps the note's floating label clear of the dropdown border
          TextField(
            controller: _note,
            maxLength: 255,
            decoration: const InputDecoration(labelText: 'Note (optional)', hintText: 'e.g. 2 bags of urea'),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _saving ? null : _save,
            icon: _saving
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.save),
            label: Text(_saving ? 'Saving…' : 'Save expense'),
          ),
        ],
      ),
    );
  }
}
