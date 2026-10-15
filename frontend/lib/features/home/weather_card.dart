import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/errors/app_failure.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';

/// "14:05" in the phone's time.
String clock(String iso) {
  final d = DateTime.tryParse(iso)?.toLocal();
  if (d == null) return '—';
  return '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

const _weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/// The highest rain chance in the coming hours and when (null when the forecast has none).
(double, String)? peakRainChance(List<Map<String, dynamic>> hours) {
  (double, String)? best;
  for (final h in hours) {
    final p = h.numOrNull('rain_probability_pct');
    if (p != null && (best == null || p > best.$1)) best = (p, h.str('time'));
  }
  return best;
}

/// Compact live weather for one farm (Home). Loads on its own so a weather problem never blocks the screen.
class FarmWeatherCard extends ConsumerStatefulWidget {
  const FarmWeatherCard({super.key, required this.farms});

  final List<Map<String, dynamic>> farms;

  @override
  ConsumerState<FarmWeatherCard> createState() => _FarmWeatherCardState();
}

class _FarmWeatherCardState extends ConsumerState<FarmWeatherCard> {
  static const _prefKey = 'weather_farm_id';
  String? _farmId;
  Future<Map<String, dynamic>>? _future;

  @override
  void initState() {
    super.initState();
    _pickInitial();
  }

  Future<void> _pickInitial() async {
    String? saved;
    try {
      saved = (await SharedPreferences.getInstance()).getString(_prefKey);
    } catch (_) {
      saved = null;
    }
    final ids = widget.farms.map((f) => f.str('id')).toList();
    final located = widget.farms.where((f) => f.numOrNull('latitude') != null).map((f) => f.str('id'));
    final id = ids.contains(saved) ? saved : (located.isNotEmpty ? located.first : (ids.isEmpty ? null : ids.first));
    if (!mounted || id == null) return;
    _select(id, save: false);
  }

  void _select(String id, {bool save = true}) {
    setState(() {
      _farmId = id;
      // the card shows the error itself; mark it handled so a fast failure is not reported as uncaught
      _future = ref.read(apiProvider).getObj('/farms/$id/weather/now')..ignore();
    });
    if (save) {
      SharedPreferences.getInstance().then((p) => p.setString(_prefKey, id)).catchError((_) => false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.farms.isEmpty) return const SizedBox.shrink();
    return SectionCard(
      title: 'Weather',
      icon: Icons.wb_cloudy_outlined,
      action: IconButton(
        tooltip: 'Refresh weather',
        icon: const Icon(Icons.refresh),
        onPressed: _farmId == null ? null : () => _select(_farmId!, save: false),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (widget.farms.length > 1)
            DropdownButton<String>(
              value: _farmId,
              isExpanded: true,
              items: [for (final f in widget.farms) DropdownMenuItem(value: f.str('id'), child: Text(f.str('name')))],
              onChanged: (v) => v == null ? null : _select(v),
            ),
          FutureBuilder<Map<String, dynamic>>(
            future: _future,
            builder: (context, snap) {
              if (_future == null || snap.connectionState != ConnectionState.done) {
                return const Padding(
                  padding: EdgeInsets.all(12),
                  child: Center(child: CircularProgressIndicator(semanticsLabel: 'Loading weather')),
                );
              }
              if (snap.hasError) {
                final f = snap.error is AppFailure ? snap.error! as AppFailure : mapDioError(snap.error!);
                return Row(
                  children: [
                    Expanded(child: Text('Weather could not be loaded: ${f.message}')),
                    TextButton(onPressed: () => _select(_farmId!, save: false), child: const Text('Retry')),
                  ],
                );
              }
              return _WeatherBody(w: snap.data!);
            },
          ),
        ],
      ),
    );
  }
}

class _WeatherBody extends StatelessWidget {
  const _WeatherBody({required this.w});

  final Map<String, dynamic> w;

  @override
  Widget build(BuildContext context) {
    final c = w.objOrNull('current');
    final small = Theme.of(context).textTheme.bodySmall;
    if (c == null) {
      return Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(w.str('note')));
    }
    final hours = w.objs('next_hours');
    final peak = peakRainChance(hours);
    final raining = c.boolVal('raining_now');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text('${number(c.numVal('temperature_c'), decimals: 0)}°C',
                style: Theme.of(context).textTheme.displaySmall,),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(c.str('condition'), style: Theme.of(context).textTheme.titleMedium),
                  if (c.numOrNull('humidity_pct') != null)
                    Text('Humidity ${number(c.numVal('humidity_pct'), decimals: 0)}%'),
                ],
              ),
            ),
            const DataKindChip('estimate'),
          ],
        ),
        const SizedBox(height: 6),
        Chip(
          avatar: Icon(raining ? Icons.umbrella : Icons.wb_sunny_outlined, size: 18),
          label: Text(raining ? 'Raining now (model estimate)' : 'No rain now (model estimate)'),
        ),
        if (peak != null)
          Text(
            'Rain chance in the next 12 hours: up to ${number(peak.$1, decimals: 0)}%'
            '${peak.$1 > 0 ? ' (around ${clock(peak.$2)})' : ''}',
          ),
        if (hours.isNotEmpty)
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (final h in hours.where((h) => hours.indexOf(h).isEven))
                  Padding(
                    padding: const EdgeInsets.only(right: 14, top: 6),
                    child: Column(
                      children: [
                        Text(clock(h.str('time')), style: small),
                        Text(
                          h.numOrNull('rain_probability_pct') == null
                              ? '—'
                              : '${number(h.numVal('rain_probability_pct'), decimals: 0)}%',
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        const Divider(),
        for (final d in w.objs('days').take(3))
          KeyValue(
            _dayName(d.str('day')),
            '${d.str('condition')} · ${number(d.numVal('tmin_c'), decimals: 0)}–${number(d.numVal('tmax_c'), decimals: 0)}°C'
            '${d.numOrNull('rain_probability_pct') == null ? '' : ' · rain ${number(d.numVal('rain_probability_pct'), decimals: 0)}%'}',
          ),
        Text('Updated ${clock(w.str('fetched_at'))}. ${w.str('note')}', style: small),
      ],
    );
  }

  static String _dayName(String iso) {
    final d = DateTime.tryParse(iso);
    if (d == null) return iso;
    final today = DateTime.now();
    if (d.year == today.year && d.month == today.month && d.day == today.day) return 'Today';
    return '${_weekdays[d.weekday - 1]} ${day(iso)}';
  }
}
