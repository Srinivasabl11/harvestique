import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';

/// Hub-operator actions for one accepted order item: receive a batch, record quality, fulfil.
class CollectionActions extends ConsumerWidget {
  const CollectionActions({super.key, required this.item, required this.batches, required this.onChanged});

  final Map<String, dynamic> item;
  final List<Map<String, dynamic>> batches;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiProvider);
    final mine = batches.where((b) => b.str('order_item_id') == item.str('id')).toList();
    final unchecked = mine.where((b) => b.objOrNull('quality') == null).toList();
    return Wrap(
      spacing: 8,
      children: [
        OutlinedButton.icon(
          icon: const Icon(Icons.move_to_inbox_outlined),
          label: const Text('Receive batch'),
          onPressed: () async {
            if (await showDialog<bool>(context: context, builder: (_) => _ReceiveDialog(item: item)) == true) onChanged();
          },
        ),
        for (final b in unchecked)
          OutlinedButton.icon(
            icon: const Icon(Icons.fact_check_outlined),
            label: Text('Quality ${b.str('code')}'),
            onPressed: () async {
              if (await showDialog<bool>(context: context, builder: (_) => QualityDialog(batch: b)) == true) onChanged();
            },
          ),
        if (mine.isNotEmpty && unchecked.isEmpty)
          FilledButton.icon(
            icon: const Icon(Icons.task_alt),
            label: const Text('Fulfil'),
            onPressed: () async {
              final ok = await runAction(
                context,
                () => api.post('/admin/order-items/${item.str('id')}/fulfil'),
                success: 'Counted towards the order',
              );
              if (ok) onChanged();
            },
          ),
      ],
    );
  }
}

class _ReceiveDialog extends ConsumerStatefulWidget {
  const _ReceiveDialog({required this.item});

  final Map<String, dynamic> item;

  @override
  ConsumerState<_ReceiveDialog> createState() => _ReceiveDialogState();
}

class _ReceiveDialogState extends ConsumerState<_ReceiveDialog> {
  final _kg = TextEditingController();
  String? _hub;
  late final Future<List<Map<String, dynamic>>> _hubs = ref.read(apiProvider).getList('/hubs');

  @override
  void dispose() {
    _kg.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Receive produce (${kg(widget.item.numVal('quantity_kg'))} committed)'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          FutureBuilder<List<Map<String, dynamic>>>(
            future: _hubs,
            builder: (context, snap) => DropdownButtonFormField<String>(
              initialValue: _hub,
              decoration: const InputDecoration(labelText: 'Hub'),
              items: [
                for (final h in snap.data ?? <Map<String, dynamic>>[])
                  DropdownMenuItem(value: h.str('id'), child: Text(h.str('name'))),
              ],
              onChanged: (v) => setState(() => _hub = v),
            ),
          ),
          FormText(controller: _kg, label: 'Weighed quantity (kg)', keyboard: TextInputType.number),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton(
          onPressed: () async {
            final q = double.tryParse(_kg.text.trim());
            if (_hub == null || q == null || q <= 0) return;
            final ok = await runAction(
              context,
              () => ref
                  .read(apiProvider)
                  .post('/admin/batches', body: {'order_item_id': widget.item.str('id'), 'hub_id': _hub, 'received_kg': q}),
              success: 'Batch recorded',
            );
            if (ok && context.mounted) Navigator.pop(context, true);
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}

class QualityDialog extends ConsumerStatefulWidget {
  const QualityDialog({super.key, required this.batch});

  final Map<String, dynamic> batch;

  @override
  ConsumerState<QualityDialog> createState() => _QualityDialogState();
}

class _QualityDialogState extends ConsumerState<QualityDialog> {
  late final _accepted = TextEditingController(text: number(widget.batch.numVal('received_kg')));
  final _rejected = TextEditingController(text: '0');
  final _defects = TextEditingController();
  String _grade = 'B';

  @override
  void dispose() {
    _accepted.dispose();
    _rejected.dispose();
    _defects.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Quality check ${widget.batch.str('code')}'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Received ${kg(widget.batch.numVal('received_kg'))}. Accepted + rejected must add up exactly.'),
            DropdownButtonFormField<String>(
              initialValue: _grade,
              decoration: const InputDecoration(labelText: 'Grade'),
              items: const [
                DropdownMenuItem(value: 'A', child: Text('A')),
                DropdownMenuItem(value: 'B', child: Text('B')),
                DropdownMenuItem(value: 'C', child: Text('C')),
              ],
              onChanged: (v) => setState(() => _grade = v ?? 'B'),
            ),
            FormText(controller: _accepted, label: 'Accepted (kg)', keyboard: TextInputType.number),
            FormText(controller: _rejected, label: 'Rejected (kg)', keyboard: TextInputType.number),
            FormText(controller: _defects, label: 'Defects / notes (optional)'),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton(
          onPressed: () async {
            final a = double.tryParse(_accepted.text.trim());
            final r = double.tryParse(_rejected.text.trim());
            if (a == null || r == null) return;
            final ok = await runAction(
              context,
              () => ref.read(apiProvider).post(
                '/admin/batches/${widget.batch.str('id')}/quality',
                body: {
                  'accepted_kg': a,
                  'rejected_kg': r,
                  if (a > 0) 'grade': _grade,
                  if (_defects.text.trim().isNotEmpty) 'defects': _defects.text.trim(),
                },
              ),
              success: 'Quality recorded',
            );
            if (ok && context.mounted) Navigator.pop(context, true);
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}
