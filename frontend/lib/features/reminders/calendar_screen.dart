import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';

/// Agenda for the next 90 days (and the last 14): sowing, predicted harvest windows (estimates), activities,
/// reminders, collections and delivery windows, each labelled with where the date comes from.
class CalendarScreen extends ConsumerWidget {
  const CalendarScreen({super.key});

  static IconData _icon(String kind) => switch (kind) {
        'sowing' => Icons.grass,
        'expected_harvest' => Icons.flag_outlined,
        'predicted_harvest_window' => Icons.insights,
        'activity' => Icons.agriculture_outlined,
        'reminder' => Icons.alarm,
        'collection' => Icons.local_shipping_outlined,
        'delivery_window' => Icons.event_available,
        _ => Icons.event,
      };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiProvider);
    final now = DateTime.now();
    final start = isoDate(now.subtract(const Duration(days: 14)));
    final end = isoDate(now.add(const Duration(days: 90)));
    return Scaffold(
      appBar: AppBar(title: const Text('Calendar')),
      body: Reloadable<List<Map<String, dynamic>>>(
        load: () => api.cached(
          'calendar',
          () async => (await api.getObj('/calendar', query: {'start': start, 'end': end})).objs('events'),
          asObjects,
        ),
        isEmpty: (e) => e.isEmpty,
        emptyMessage: 'Nothing scheduled in the next 90 days.',
        builder: (context, events, reload) => ListView.builder(
          itemCount: events.length,
          itemBuilder: (context, i) {
            final e = events[i];
            final showDate = i == 0 || events[i - 1].str('start') != e.str('start');
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (showDate)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
                    child: Text(day(e.str('start')), style: Theme.of(context).textTheme.titleSmall),
                  ),
                ListTile(
                  leading: Icon(_icon(e.str('kind'))),
                  title: Text(e.str('title')),
                  subtitle: e.strOrNull('end') == null ? null : Text('until ${day(e.str('end'))}'),
                  trailing: DataKindChip(e.str('data_kind')),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}
