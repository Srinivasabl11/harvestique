import 'package:flutter/material.dart';

import '../../core/util/format.dart';
import '../../core/util/json.dart';

/// Display order of crop categories (server values).
const cropCategoryOrder = [
  'vegetable',
  'fruit',
  'cereal',
  'pulse',
  'oilseed',
  'spice',
  'cash_crop',
  'plantation',
  'flower',
  'fodder',
  'medicinal',
  'other',
];

const _categoryNames = {
  'vegetable': 'Vegetables',
  'fruit': 'Fruits',
  'cereal': 'Cereals & millets',
  'pulse': 'Pulses',
  'oilseed': 'Oilseeds',
  'spice': 'Spices',
  'cash_crop': 'Cash crops',
  'plantation': 'Plantation crops',
  'flower': 'Flowers',
  'fodder': 'Fodder',
  'medicinal': 'Medicinal plants',
  'other': 'Other',
};

/// Readable name of a crop category ("cereal" -> "Cereals & millets").
String categoryName(String raw) => _categoryNames[raw] ?? label(raw);

/// Crops matching a search (English or Kannada name, another common name such as "finger millet" for Ragi, or the
/// scientific name) and, when given, a category; sorted by name.
List<Map<String, dynamic>> filterCrops(List<Map<String, dynamic>> all, String query, String? category) {
  final q = query.trim().toLowerCase();
  bool matches(Map<String, dynamic> c) => [
        c.str('name'),
        c.str('local_name'),
        c.str('scientific_name'),
        ...c.strs('aliases'),
      ].any((name) => name.toLowerCase().contains(q));
  return all
      .where((c) => category == null || c.str('category') == category)
      .where((c) => q.isEmpty || matches(c))
      .toList()
    ..sort((a, b) => a.str('name').toLowerCase().compareTo(b.str('name').toLowerCase()));
}

/// "All" plus one chip per category that has crops, with counts.
class CropCategoryChips extends StatelessWidget {
  const CropCategoryChips({super.key, required this.crops, required this.selected, required this.onSelected});

  final List<Map<String, dynamic>> crops;
  final String? selected;
  final ValueChanged<String?> onSelected;

  @override
  Widget build(BuildContext context) {
    final counts = <String, int>{};
    for (final c in crops) {
      counts.update(c.str('category'), (n) => n + 1, ifAbsent: () => 1);
    }
    final present = [
      ...cropCategoryOrder.where(counts.containsKey),
      ...counts.keys.where((k) => !cropCategoryOrder.contains(k)),
    ];
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: ChoiceChip(
              label: Text('All (${crops.length})'),
              selected: selected == null,
              onSelected: (_) => onSelected(null),
            ),
          ),
          for (final k in present)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ChoiceChip(
                label: Text('${categoryName(k)} (${counts[k]})'),
                selected: selected == k,
                onSelected: (on) => onSelected(on ? k : null),
              ),
            ),
        ],
      ),
    );
  }
}
