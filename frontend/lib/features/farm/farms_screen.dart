import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../planning/plans_screen.dart';
import 'farm_detail_screen.dart';

/// My Farm: farms, plus entry points to income planning and inventory.
class FarmsScreen extends ConsumerStatefulWidget {
  const FarmsScreen({super.key});

  @override
  ConsumerState<FarmsScreen> createState() => _FarmsScreenState();
}

class _FarmsScreenState extends ConsumerState<FarmsScreen> {
  Key _key = UniqueKey();
  bool _showArchived = false;

  void _refresh() => setState(() => _key = UniqueKey());

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiProvider);
    return Reloadable<List<Map<String, dynamic>>>(
      key: _key,
      load: () => api.cached(
        'farms:$_showArchived',
        () => api.getPage('/farms', query: {if (_showArchived) 'include_archived': true}),
        asObjects,
      ),
      builder: (context, farms, reload) => ListView(
        padding: const EdgeInsets.only(bottom: 96),
        children: [
          for (final f in farms)
            Card(
              margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              child: ListTile(
                leading: const Icon(Icons.landscape_outlined),
                title: Text(f.boolVal('is_active', true) ? f.str('name') : '${f.str('name')} (archived)'),
                subtitle: Text('${number(f.numVal('total_area_acres'))} acres'
                    '${f.str('village').isEmpty ? '' : ' · ${f.str('village')}'}'
                    '${f.numOrNull('latitude') == null ? ' · no location (weather unavailable)' : ''}'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () async {
                  await Navigator.of(context)
                      .push(MaterialPageRoute<void>(builder: (_) => FarmDetailScreen(farmId: f.str('id'))));
                  await reload();
                },
              ),
            ),
          if (farms.isEmpty) const EmptyPanel(message: 'No farms yet. Add your first farm.', icon: Icons.landscape_outlined),
          SwitchListTile(
            title: const Text('Show archived farms'),
            value: _showArchived,
            onChanged: (v) => setState(() {
              _showArchived = v;
              _key = UniqueKey();
            }),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: FilledButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Add farm'),
              onPressed: () async {
                final created = await showDialog<bool>(context: context, builder: (_) => const AddFarmDialog());
                if (created == true) _refresh();
              },
            ),
          ),
          ListTile(
            leading: const Icon(Icons.calculate_outlined),
            title: const Text('Income plans'),
            subtitle: const Text('Low, expected and high margins for your crop plans'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const PlansScreen())),
          ),
        ],
      ),
    );
  }
}

class AddFarmDialog extends ConsumerStatefulWidget {
  const AddFarmDialog({super.key});

  @override
  ConsumerState<AddFarmDialog> createState() => _AddFarmDialogState();
}

class _AddFarmDialogState extends ConsumerState<AddFarmDialog> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _area = TextEditingController();
  final _village = TextEditingController();
  final _lat = TextEditingController();
  final _lon = TextEditingController();

  @override
  void dispose() {
    for (final c in [_name, _area, _village, _lat, _lon]) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add farm'),
      content: Form(
        key: _form,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              FormText(controller: _name, label: 'Farm name', validator: requiredText),
              FormText(controller: _area, label: 'Total area (acres)', keyboard: TextInputType.number, validator: positiveNumber),
              FormText(controller: _village, label: 'Village (optional)'),
              FormText(
                controller: _lat,
                label: 'Latitude (optional, for weather)',
                keyboard: TextInputType.number,
                validator: optionalNumber,
              ),
              FormText(
                controller: _lon,
                label: 'Longitude (optional)',
                keyboard: TextInputType.number,
                validator: optionalNumber,
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton(
          onPressed: () async {
            if (!_form.currentState!.validate()) return;
            final lat = double.tryParse(_lat.text.trim());
            final lon = double.tryParse(_lon.text.trim());
            final ok = await runAction(
              context,
              () => ref.read(apiProvider).post(
                '/farms',
                body: {
                  'name': _name.text.trim(),
                  'total_area_acres': double.parse(_area.text.trim()),
                  if (_village.text.trim().isNotEmpty) 'village': _village.text.trim(),
                  if (lat != null && lon != null) 'latitude': double.parse(lat.toStringAsFixed(6)),
                  if (lat != null && lon != null) 'longitude': double.parse(lon.toStringAsFixed(6)),
                },
              ),
              success: 'Farm added',
            );
            if (ok && context.mounted) Navigator.pop(context, true);
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}
