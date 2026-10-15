import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/config/app_config.dart';
import '../../core/network/api_client.dart';
import '../../core/util/format.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../auth/auth_controller.dart';

/// Advisory crop-health check from a photo. Shows probabilities, never a diagnosis.
class CropHealthScreen extends ConsumerStatefulWidget {
  const CropHealthScreen({super.key, this.cycleId});

  final String? cycleId;

  @override
  ConsumerState<CropHealthScreen> createState() => _CropHealthScreenState();
}

class _CropHealthScreenState extends ConsumerState<CropHealthScreen> {
  Map<String, dynamic>? _result;
  bool _busy = false;

  Future<void> _pick(ImageSource source) async {
    final file = await ImagePicker().pickImage(
        source: source, maxWidth: 1600, maxHeight: 1600, imageQuality: 85,);
    if (file == null || !mounted) return;
    setState(() {
      _busy = true;
      _result = null;
    });
    final lang = ref.read(authProvider).language;
    await runAction(context, () async {
      final bytes = await file.readAsBytes();
      final res = await ref.read(apiProvider).upload(
            '/crop-health/analyze',
            field: 'image',
            bytes: bytes,
            filename: file.name,
            fields: {
              'language': lang,
              if (widget.cycleId != null) 'crop_cycle_id': widget.cycleId!,
            },
            receiveTimeout: AppConfig.photoCheckTimeout,
          );
      if (mounted) setState(() => _result = res);
    });
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final r = _result;
    return Scaffold(
      appBar: AppBar(title: const Text('Crop health check')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          const Text(
            'Take a clear, close photo of the affected leaves in daylight. The result is a suggestion, not a diagnosis.',
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: _busy ? null : () => _pick(ImageSource.camera),
                  icon: const Icon(Icons.photo_camera),
                  label: const Text('Camera'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _busy ? null : () => _pick(ImageSource.gallery),
                  icon: const Icon(Icons.photo_library_outlined),
                  label: const Text('Gallery'),
                ),
              ),
            ],
          ),
          if (_busy)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Column(
                children: [
                  CircularProgressIndicator(
                      semanticsLabel: 'Checking the photo',),
                  SizedBox(height: 12),
                  Text(
                      'Checking the photo. This can take up to a minute or two.',
                      textAlign: TextAlign.center,),
                ],
              ),
            ),
          if (r != null) CropHealthResult(r: r),
        ],
      ),
    );
  }
}

/// Card title: no health label for a colour-only check, "Unclear" when nothing could be judged, and "Uncertain"
/// when the AI saw signs but with low confidence (e.g. a far-away or poor photo).
String cropHealthTitle(Map<String, dynamic> r) {
  final features = r.obj('features');
  if (features['mode'] == 'measurements_only') return 'Colour check (no health label)';
  final name = label(r.str('label'));
  if (r.str('label') == 'unknown') return 'Unclear from this photo';
  if (features['ai_confidence'] == 'low') return 'Uncertain: $name';
  return 'Most likely: $name';
}

/// Whole percentages that add up to exactly 100 (largest-remainder rounding). Rounding each bar on its own showed
/// 65 + 21 + 5 + 5 + 5 = 101 % for some results.
Map<String, int> wholePercents(Map<String, dynamic> values) {
  final exact = <String, double>{
    for (final e in values.entries) e.key: (((e.value as num?) ?? 0).toDouble()).clamp(0, double.infinity).toDouble(),
  };
  final total = exact.values.fold<double>(0, (a, b) => a + b);
  if (total <= 0) return {for (final k in exact.keys) k: 0};
  final scaled = {for (final e in exact.entries) e.key: e.value * 100 / total};
  final out = {for (final e in scaled.entries) e.key: e.value.floor()};
  final order = scaled.keys.toList()
    ..sort((a, b) {
      final byRest = (scaled[b]! - out[b]!).compareTo(scaled[a]! - out[a]!);
      return byRest != 0 ? byRest : scaled[b]!.compareTo(scaled[a]!);
    });
  var missing = 100 - out.values.fold<int>(0, (a, b) => a + b);
  for (final k in order) {
    if (missing <= 0) break;
    out[k] = out[k]! + 1;
    missing--;
  }
  return out;
}

class CropHealthResult extends StatelessWidget {
  const CropHealthResult({super.key, required this.r});

  final Map<String, dynamic> r;

  @override
  Widget build(BuildContext context) {
    final percents = wholePercents(r.obj('probabilities'));
    final probs = percents.entries.toList()..sort((a, b) => b.value.compareTo(a.value));
    final flags = r.strs('quality_flags');
    final features = r.obj('features');
    final measurementsOnly = features['mode'] == 'measurements_only';
    final symptoms = features['symptoms'] is List
        ? (features['symptoms'] as List).map((e) => '$e').toList()
        : <String>[];
    // structured report (newer results); older stored results show the original layout
    final analysis = features['analysis'] is Map ? Map<String, dynamic>.from(features['analysis'] as Map) : null;
    final small = Theme.of(context).textTheme.bodySmall;
    return SectionCard(
      title: cropHealthTitle(r),
      icon: Icons.eco_outlined,
      action: const DataKindChip('estimate'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (analysis != null) ConditionScore(condition: analysis.obj('condition')),
          if (analysis == null && symptoms.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(
                  'Signs the AI noticed: ${symptoms.map(label).join(', ')}',),
            ),
          if (!measurementsOnly) ...[
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('Category leaning (AI estimate, not a measured probability)', style: small),
            ),
            for (final e in probs)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: [
                    SizedBox(width: 150, child: Text(label(e.key))),
                    Expanded(
                        child: LinearProgressIndicator(
                            value: e.value / 100,
                            minHeight: 8,),),
                    SizedBox(
                      width: 48,
                      child: Text('${e.value}%', textAlign: TextAlign.end),
                    ),
                  ],
                ),
              ),
          ],
          if (flags.isNotEmpty && analysis == null)
            Text('Photo: ${flags.map(label).join(', ')} (see the tip below)',
                style: const TextStyle(fontWeight: FontWeight.w600),),
          if (analysis != null)
            for (final s in analysis.objs('sections')) ReportSection(section: s),
          const SizedBox(height: 8),
          Text(r.str('explanation')),
          if (analysis == null) ...[
            const SizedBox(height: 4),
            Text(r.str('advice'),
                style: const TextStyle(fontWeight: FontWeight.w600),),
          ],
          const SizedBox(height: 8),
          Text(r.str('disclaimer'), style: small),
          Text('Model: ${r.str('model_name')} ${r.str('model_version')}', style: small),
        ],
      ),
    );
  }
}

/// The visual condition score out of 10, or why no score was given. It rates what is visible in the photo; it is
/// not the chance of a disease and not how sure the AI is.
class ConditionScore extends StatelessWidget {
  const ConditionScore({super.key, required this.condition});

  final Map<String, dynamic> condition;

  @override
  Widget build(BuildContext context) {
    final score = condition['score'];
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (score is num)
            Text('${score.toInt()}/${condition['out_of'] ?? 10}  ${condition.str('text')}',
                style: theme.textTheme.titleMedium,
                semanticsLabel: 'Visual condition ${score.toInt()} out of 10. ${condition.str('text')}',)
          else
            Text(condition.str('text'), style: const TextStyle(fontWeight: FontWeight.w600)),
          if (score is num) Text(condition.str('method'), style: theme.textTheme.bodySmall),
        ],
      ),
    );
  }
}

class ReportSection extends StatelessWidget {
  const ReportSection({super.key, required this.section});

  final Map<String, dynamic> section;

  @override
  Widget build(BuildContext context) {
    final items = section.strs('items');
    if (items.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(section.str('title'), style: const TextStyle(fontWeight: FontWeight.w600)),
          for (final item in items) Text('• $item'),
        ],
      ),
    );
  }
}
