import 'package:flutter/material.dart';

import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';

/// Buyer-facing words for matching results and demand progress. The codes come from the server
/// (backend domain/pooling/matching.py and shortage.py); an unknown code is still shown, via [label].

const _reasonTexts = {
  'crop_mismatch': 'a different crop',
  'grade_below_minimum': 'expected grade below your minimum',
  'not_opted_in': 'the farmer has not offered it to buyers',
  'lot_not_open': 'no prediction yet, or the crop was abandoned',
  'no_available_quantity': 'all of it is already committed',
  'window_no_overlap': 'harvest dates do not fit your delivery window',
  'confidence_below_minimum': 'prediction confidence below your minimum',
  'risk_above_maximum': 'crop risk above your maximum',
  'location_unknown': 'farm location unknown (you set a maximum distance)',
  'too_far': 'farther than your maximum distance',
};

/// Why a farm lot was not used, in plain words.
String reasonText(String code) => _reasonTexts[code] ?? label(code);

const _nextStepTexts = {
  'create_pool': 'Reserve the eligible supply now (create a harvest pool). Farmers confirm after you place the order.',
  'wait_for_supply':
      'Keep the demand open. Farmers growing this crop have been told, and new supply they offer can be added later.',
  'revise_dates': 'Change the delivery dates: some harvests fall outside your window.',
  'widen_distance': 'Allow a larger distance from your delivery point.',
  'accept_lower_grade': 'Accept a lower minimum grade.',
  'relax_risk_limits': 'Relax the confidence or risk limits.',
  'choose_other_crop':
      'Create a demand for a different crop. Only you can decide this: Harvestique never substitutes a crop.',
};

String nextStepText(String code) => _nextStepTexts[code] ?? label(code);

/// "full", "partial" or "none" for a matching result. Uses the server's answer; an older server without it is
/// worked out from the same numbers (eligible supply against the quantity needed).
String fulfilmentOf(Map<String, dynamic> m) {
  final f = m.strOrNull('fulfilment');
  final eligible = m.numVal('eligible_supply_kg');
  final need = m.numVal('need_kg');
  final shortage = m.numOrNull('shortage_kg') ?? m.numVal('shortfall_kg');
  // the server sends "none" as a default when it has not filled the field; trust it only if the numbers agree
  if (f == 'full' || f == 'partial') return f!;
  if (f == 'none' && eligible <= 0) return 'none';
  if (need > 0 && shortage <= 0 && eligible >= need) return 'full';
  return eligible > 0 ? 'partial' : 'none';
}

/// Shortage for a matching result: the server's figure, never below zero.
double shortageOf(Map<String, dynamic> m) {
  final s = m.numOrNull('shortage_kg') ?? m.numOrNull('shortfall_kg');
  if (s != null) return s < 0 ? 0 : s;
  final gap = m.numVal('need_kg') - m.numVal('eligible_supply_kg');
  return gap > 0 ? gap : 0;
}

/// The quantity of a demand not covered by supply: `remaining_kg` once pooled, the live `shortage_kg` before.
/// Zero for a closed demand, or when the server does not send either (older server).
double demandShortage(Map<String, dynamic> d) {
  const closed = {'cancelled', 'fulfilled', 'partially_fulfilled'};
  if (closed.contains(d.strOrNull('stage') ?? d.str('status'))) return 0;
  final v = d.numOrNull('remaining_kg') ?? d.numOrNull('shortage_kg') ?? 0;
  return v > 0 ? v : 0;
}

class StageInfo {
  const StageInfo(this.title, this.detail, this.icon, this.level);

  final String title;
  final String detail;
  final IconData icon;

  /// low = good, medium = needs attention, high = problem, '' = neutral
  final String level;
}

/// The buyer-facing state of a demand. Uses the server's `stage`; an older server is approximated from `status`.
StageInfo demandStage(Map<String, dynamic> d) {
  final stage = d.strOrNull('stage') ??
      switch (d.str('status')) {
        'cancelled' => 'cancelled',
        'pooled' => 'supply_reserved',
        _ => 'open',
      };
  return switch (stage) {
    'open' => const StageInfo(
        'Open: nothing reserved yet',
        'Matching supply is shown below. Nothing is reserved until you create a harvest pool.',
        Icons.search,
        '',
      ),
    'matching_supply_available' => const StageInfo(
        'Matching supply available',
        'Current eligible predictions cover the whole quantity. Nothing is reserved until you create a harvest pool.',
        Icons.check_circle_outline,
        'low',
      ),
    'supply_reserved' => const StageInfo(
        'Matching supply reserved',
        'Predicted supply is reserved for you. Place the order so the farmers can confirm.',
        Icons.hub_outlined,
        'low',
      ),
    'partially_matched' => const StageInfo(
        'Partially matched: shortage remaining',
        'Eligible supply covers only part of the quantity. The rest stays visible as a shortage.',
        Icons.warning_amber_rounded,
        'medium',
      ),
    'no_matching_supply' => const StageInfo(
        'No matching supply available',
        'No farm has eligible predicted supply for this demand yet.',
        Icons.report_outlined,
        'high',
      ),
    'awaiting_farmer_confirmation' => const StageInfo(
        'Awaiting farmer confirmation',
        'The order is placed. Each farm must accept its share before it counts as confirmed.',
        Icons.hourglass_top,
        'medium',
      ),
    'confirmed' => const StageInfo(
        'Confirmed',
        'The farms accepted. Quantities are still predictions until the harvest is weighed.',
        Icons.verified_outlined,
        'low',
      ),
    'reallocation_required' => const StageInfo(
        'Supply changed: reallocation required',
        'A farm\'s prediction fell or a farm declined, and replacement supply does not yet cover it all.',
        Icons.sync_problem,
        'high',
      ),
    'in_fulfilment' => const StageInfo(
        'In fulfilment',
        'Produce is being collected and quality-checked.',
        Icons.local_shipping_outlined,
        'low',
      ),
    'fulfilled' => const StageInfo('Fulfilled', 'Delivered and accepted at the quality check.', Icons.task_alt, 'low'),
    'partially_fulfilled' => const StageInfo(
        'Partially fulfilled',
        'Less than the ordered quantity was delivered and accepted.',
        Icons.rule,
        'medium',
      ),
    'cancelled' => const StageInfo('Cancelled', 'Farmers no longer see this demand.', Icons.block, ''),
    _ => StageInfo(label(stage), '', Icons.info_outline, ''),
  };
}

/// A one-line chip with a demand's stage (for lists).
class StageChip extends StatelessWidget {
  const StageChip({super.key, required this.demand});

  final Map<String, dynamic> demand;

  @override
  Widget build(BuildContext context) {
    final s = demandStage(demand);
    final color = s.level.isEmpty ? Theme.of(context).colorScheme.onSurfaceVariant : levelColor(s.level);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(s.icon, size: 16, color: color),
        const SizedBox(width: 4),
        Flexible(child: Text(s.title, style: TextStyle(color: color, fontWeight: FontWeight.w600))),
      ],
    );
  }
}

/// Full / partial / no supply for a matching result: the numbers, why farm lots were left out, and what the
/// buyer can do next. Every quantity is a pessimistic (p10) prediction, never harvested produce.
class SupplySummaryCard extends StatelessWidget {
  const SupplySummaryCard({super.key, required this.matches, this.pooled = false});

  final Map<String, dynamic> matches;

  /// The demand already has a pool: the result is about the part still not covered.
  final bool pooled;

  @override
  Widget build(BuildContext context) {
    final m = matches;
    final f = fulfilmentOf(m);
    final shortage = shortageOf(m);
    final (title, icon, level) = switch (f) {
      'full' => ('Matching supply available', Icons.check_circle_outline, 'low'),
      'partial' => ('Partially matched: shortage remaining', Icons.warning_amber_rounded, 'medium'),
      _ => ('No matching supply available', Icons.report_outlined, 'high'),
    };
    final explanation = m.strs('explanation');
    final excluded = m.obj('excluded_reasons').entries.toList()
      ..sort((a, b) => ((b.value as num?) ?? 0).compareTo((a.value as num?) ?? 0));
    final steps = m.strs('next_steps').where((s) => !(pooled && s == 'create_pool')).toList();
    final eligibleLots = m.intVal('eligible_count');
    return SectionCard(
      title: pooled ? 'Supply for the part still needed' : title,
      icon: icon,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (pooled) Text(title, style: TextStyle(color: levelColor(level), fontWeight: FontWeight.w600)),
          KeyValue(pooled ? 'Still needed' : 'Needed', kg(m.numVal('need_kg'))),
          KeyValue(
            'Eligible predicted supply',
            '${kg(m.numVal('eligible_supply_kg'))} · $eligibleLots farm lot${eligibleLots == 1 ? '' : 's'}',
            kind: 'estimate',
          ),
          KeyValue('Shortage', shortage > 0 ? kg(shortage) : 'none'),
          const SizedBox(height: 4),
          if (explanation.isNotEmpty)
            for (final line in explanation) Text(line)
          else
            Text(
              f == 'full'
                  ? 'The quantity can be met from current predictions. Only this crop is ever matched.'
                  : f == 'partial'
                      ? 'Current predictions cannot cover the whole quantity. Only this crop is ever matched.'
                      : 'No eligible supply of this crop yet. Other crops are never matched.',
            ),
          if (excluded.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Farm lots not used', style: Theme.of(context).textTheme.titleSmall),
            for (final e in excluded) Text('• ${e.value} · ${reasonText(e.key)}'),
          ],
          if (steps.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('What you can do', style: Theme.of(context).textTheme.titleSmall),
            for (final s in steps) Text('• ${nextStepText(s)}'),
          ],
        ],
      ),
    );
  }
}
