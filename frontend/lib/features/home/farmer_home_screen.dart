import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../assistant/assistant_screen.dart';
import '../auth/auth_controller.dart';
import '../crop_health/crop_health_screen.dart';
import 'quotes/quote_hero.dart';
import 'weather_card.dart';

/// Today at a glance, built only from the farmer's own data (cached for offline use).
class FarmerHomeScreen extends ConsumerWidget {
  const FarmerHomeScreen({super.key});

  Future<Map<String, dynamic>> _load(ApiClient api) async {
    final results = await Future.wait([
      api.getPage('/farms'),
      api.getPage('/participations', query: {'status': 'pending'}),
      api.getPage('/reminders', query: {'status': 'pending', 'limit': 5}),
      api.getPage('/inventory/lots'),
    ]);
    final farms = results[0];
    final located = farms.where((f) => f.numOrNull('latitude') != null).toList();
    Map<String, dynamic>? risk;
    if (farms.isNotEmpty) {
      try {
        risk = await api.getObj('/farms/${farms.first.str('id')}/risk');
      } catch (_) {
        risk = null;
      }
    }
    return {
      'farms': farms,
      'requests': results[1],
      'reminders': results[2],
      'lots': results[3],
      if (risk != null) 'risk': risk,
      'farm_name': located.isNotEmpty ? located.first.str('name') : (farms.isNotEmpty ? farms.first.str('name') : ''),
    };
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiProvider);
    final name = ref.watch(authProvider).name;
    return Reloadable<Map<String, dynamic>>(
      // the hero needs no server data: it also shows while loading and when the server is unreachable
      header: const HarvestiqueQuoteHero(),
      load: () =>
          api.cached('farmer_home', () => _load(api), (j) => j is Map<String, dynamic> ? j : <String, dynamic>{}),
      builder: (context, d, reload) {
        final requests = d.objs('requests');
        final reminders = d.objs('reminders');
        final lots = d.objs('lots');
        final atRisk = lots.where((l) => l.str('status') == 'at_risk').length;
        return ListView(
          padding: const EdgeInsets.only(bottom: 96),
          children: [
            const HarvestiqueQuoteHero(),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
              child: Text('Namaskara, ${name.split(' ').first}', style: Theme.of(context).textTheme.headlineSmall),
            ),
            if (d.objs('farms').isEmpty)
              const SectionCard(
                title: 'Get started',
                icon: Icons.flag_outlined,
                child: Text(
                  'Open "My Farm" to add your farm, plots and crops. Predictions, buyers and reminders follow from there.',
                ),
              ),
            FarmWeatherCard(farms: d.objs('farms')),
            if (d.objOrNull('risk') != null) _RiskCard(risk: d.obj('risk'), farm: d.str('farm_name')),
            SectionCard(
              title: 'Supply requests waiting for you',
              icon: Icons.handshake_outlined,
              child: Text(
                requests.isEmpty
                    ? 'None right now.'
                    : '${requests.length} request(s): ${requests.map((r) => '${r.str('crop_name')} ${kg(r.numVal('quantity_kg'))}').join(', ')}. Open Market to accept or decline.',
              ),
            ),
            if (atRisk > 0)
              SectionCard(
                title: 'Harvest commitments at risk',
                icon: Icons.warning_amber_rounded,
                child: Text('$atRisk lot(s) are committed beyond what the latest prediction can safely promise. '
                    'Harvestique tries to replace the difference from other farms.'),
              ),
            SectionCard(
              title: 'Next reminders',
              icon: Icons.alarm,
              child: reminders.isEmpty
                  ? const Text('No pending reminders.')
                  : Column(
                      children: [
                        for (final r in reminders.take(3)) KeyValue(r.str('title'), dateTime(r.str('due_at'))),
                      ],
                    ),
            ),
            Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.eco_outlined),
                      label: const Text('Check crop health'),
                      onPressed: () =>
                          Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const CropHealthScreen())),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton.icon(
                      icon: const Icon(Icons.mic),
                      label: const Text('Ask assistant'),
                      onPressed: () =>
                          Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const AssistantScreen())),
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

class _RiskCard extends StatelessWidget {
  const _RiskCard({required this.risk, required this.farm});

  final Map<String, dynamic> risk;
  final String farm;

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: 'Farm risk · $farm',
      icon: Icons.shield_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          RiskChip(level: risk.str('overall_level'), score: risk.numOrNull('overall_score')),
          Text(risk.str('note'), style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
