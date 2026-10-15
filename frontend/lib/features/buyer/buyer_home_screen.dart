import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../home/quotes/karnataka_quote_hero.dart';
import 'search_screen.dart';

/// Future supply on offer per crop: sums of farmers' pessimistic (p10) predictions on opted-in lots.
class BuyerHomeScreen extends ConsumerWidget {
  const BuyerHomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiProvider);
    return Reloadable<List<Map<String, dynamic>>>(
      // the hero needs no server data: it also shows while loading and when the server is unreachable
      header: const KarnatakaQuoteHero(),
      load: () => api.cached('supply', () => api.getList('/market/supply'), asObjects),
      builder: (context, rows, reload) => ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          const KarnatakaQuoteHero(),
          Padding(
            padding: const EdgeInsets.all(12),
            child: FilledButton.icon(
              icon: const Icon(Icons.search),
              label: const Text('Search future harvests'),
              onPressed: () =>
                  Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const SearchScreen())),
            ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16),
            child: Text(
                'Quantities are farmers\' pessimistic (p10) predictions that are not yet committed. They are estimates and can change; '
                'Harvestique reallocates automatically when they fall. No prices are shown.'),
          ),
          if (rows.isEmpty) const EmptyPanel(message: 'No future supply is on offer right now.'),
          for (final r in rows)
            Card(
              margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              child: ListTile(
                leading: const Icon(Icons.spa_outlined),
                title: Text('${r.str('crop_name')} · ${kg(r.numVal('available_kg'))}'),
                subtitle: Text(
                  '${r.intVal('lots')} farm lot(s) · harvest ${day(r.strOrNull('earliest_harvest_start'))} – ${day(r.strOrNull('latest_harvest_end'))}',
                ),
                trailing: const DataKindChip('estimate'),
              ),
            ),
        ],
      ),
    );
  }
}
