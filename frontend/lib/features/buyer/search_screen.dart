import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import 'supply_status.dart';

/// Why a harvest search cannot run yet, or null when it can.
String? validateHarvestSearch({required String? cropId, required String quantity}) {
  if (cropId == null) return 'Choose a crop.';
  final q = double.tryParse(quantity.trim());
  if (q == null || q <= 0) return 'Enter the quantity you need in kg (a number above 0).';
  if (q > 10000000) return 'That quantity is too large.';
  return null;
}

/// Search eligible future harvests (opted-in farm lots, pseudonymous, ranked by the allocation score).
class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});

  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  final _qty = TextEditingController(text: '1000');
  String? _crop;
  String _grade = 'C';
  DateTime _from = DateTime.now().add(const Duration(days: 14));
  DateTime _to = DateTime.now().add(const Duration(days: 90));
  Future<Map<String, dynamic>>? _result;
  late Future<List<Map<String, dynamic>>> _crops = _loadCrops();
  String? _problem;
  bool _searching = false;

  Future<List<Map<String, dynamic>>> _loadCrops() => ref.read(apiProvider).getAll('/crops')..ignore();

  @override
  void dispose() {
    _qty.dispose();
    super.dispose();
  }

  void _search() {
    if (_searching) return;
    final problem = validateHarvestSearch(cropId: _crop, quantity: _qty.text);
    setState(() => _problem = problem);
    if (problem != null) return;
    final q = double.parse(_qty.text.trim());
    final request = ref.read(apiProvider).getObj(
        '/market/harvests',
        query: {
          'crop_id': _crop,
          'quantity_kg': q,
          'window_start': isoDate(_from),
          'window_end': isoDate(_to),
          'min_grade': _grade,
        },
      );
    setState(() {
      _searching = true;
      _result = request..ignore(); // errors are shown by the FutureBuilder
    });
    request.then((_) {}, onError: (_) {}).whenComplete(() {
      if (mounted) setState(() => _searching = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Search future harvests')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          FutureBuilder<List<Map<String, dynamic>>>(
            future: _crops,
            builder: (context, snap) {
              if (snap.hasError) {
                return ErrorPanel(error: snap.error!, onRetry: () => setState(() {
                        _crops = _loadCrops();
                      }),);
              }
              final crops = [...snap.data ?? <Map<String, dynamic>>[]]
                ..sort((a, b) => a.str('name').compareTo(b.str('name')));
              return DropdownButtonFormField<String>(
                initialValue: _crop,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: 'Crop',
                  helperText: snap.hasData ? null : 'Loading crops…',
                ),
                items: [
                  for (final c in crops)
                    DropdownMenuItem(
                      value: c.str('id'),
                      child: Text(
                        c.str('local_name').isEmpty ? c.str('name') : '${c.str('name')} · ${c.str('local_name')}',
                      ),
                    ),
                ],
                onChanged: (v) => setState(() {
                  _crop = v;
                  _problem = null;
                }),
              );
            },
          ),
          FormText(controller: _qty, label: 'Quantity needed (kg)', keyboard: TextInputType.number),
          DropdownButtonFormField<String>(
            initialValue: _grade,
            decoration: const InputDecoration(labelText: 'Minimum grade'),
            items: const [
              DropdownMenuItem(value: 'A', child: Text('A')),
              DropdownMenuItem(value: 'B', child: Text('B or better')),
              DropdownMenuItem(value: 'C', child: Text('Any (C or better)')),
            ],
            onChanged: (v) => setState(() => _grade = v ?? 'C'),
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Delivery window'),
            subtitle: Text('${day(isoDate(_from))} – ${day(isoDate(_to))}'),
            trailing: const Icon(Icons.date_range),
            onTap: () async {
              final r = await showDateRangePicker(
                context: context,
                firstDate: DateTime.now(),
                lastDate: DateTime.now().add(const Duration(days: 730)),
                initialDateRange: DateTimeRange(start: _from, end: _to),
              );
              if (r != null) {
                setState(() {
                  _from = r.start;
                  _to = r.end;
                });
              }
            },
          ),
          if (_problem != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Text(_problem!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
          FilledButton.icon(
            onPressed: _searching ? null : _search,
            icon: const Icon(Icons.search),
            label: Text(_searching ? 'Searching…' : 'Search'),
          ),
          if (_result != null)
            FutureBuilder<Map<String, dynamic>>(
              future: _result,
              builder: (context, snap) {
                if (snap.hasError) return ErrorPanel(error: snap.error!, onRetry: _search);
                if (!snap.hasData) {
                  return const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(semanticsLabel: 'Loading')));
                }
                final r = snap.data!;
                final matches = r.objs('matches');
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 12),
                    SupplySummaryCard(matches: r),
                    const Text(
                      'This is a search only: nothing is reserved. Create a demand to keep the request open, '
                      'reserve supply and tell farmers who grow this crop.',
                    ),
                    Text(r.str('note'), style: Theme.of(context).textTheme.bodySmall),
                    for (final m in matches) MatchTile(match: m),
                  ],
                );
              },
            ),
        ],
      ),
    );
  }
}

class MatchTile extends StatelessWidget {
  const MatchTile({super.key, required this.match});

  final Map<String, dynamic> match;

  @override
  Widget build(BuildContext context) {
    final m = match;
    final reasons = m.strs('reasons');
    return Card(
      child: ExpansionTile(
        leading: Icon(
          m.boolVal('eligible') ? Icons.check_circle_outline : Icons.block,
          color: m.boolVal('eligible') ? Colors.green : Colors.grey,
        ),
        title: Text('Farm ${m.str('farm_ref')} · ${kg(m.numVal('available_kg'))}'),
        subtitle: Text(
          'Score ${number(m.numVal('score'))} · harvest ${day(m.str('window_start'))} – ${day(m.str('window_end'))}'
          '${m.strOrNull('grade') == null ? '' : '\n${gradeLine(m)}'}',
        ),
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Column(
              children: [
                if (reasons.isNotEmpty) KeyValue('Not eligible because', reasons.map(reasonText).join('; ')),
                KeyValue('Confidence', '${number(m.numVal('confidence'))}/100', kind: 'estimate'),
                KeyValue(
                  'Risk',
                  m.numOrNull('risk') == null ? 'not assessed' : '${number(m.numVal('risk'))}/100',
                  kind: 'estimate',
                ),
                KeyValue('Reliability (past predictions)', number(m.numVal('reliability'), decimals: 2)),
                if (m.numOrNull('distance_km') != null) KeyValue('Distance', '${number(m.numVal('distance_km'))} km'),
                for (final c in m.obj('components').entries)
                  KeyValue('Score part: ${label(c.key)}', number(c.value is num ? c.value as num : null)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// The lot's grade and how the farmer arrived at it. Both are the farmer's own (indicative) grades; the hub's quality
/// check on delivery decides acceptance.
String gradeLine(Map<String, dynamic> m) => m.str('grade_basis') == 'farmer_graded'
    ? 'Grade ${m.str('grade')} · graded by the farmer after harvest'
    : "Grade ${m.str('grade')} · farmer's expectation (not graded yet)";
