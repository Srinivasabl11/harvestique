import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/config/app_config.dart';
import '../../core/network/api_client.dart';
import '../../core/util/json.dart';
import '../../core/widgets/common.dart';
import '../auth/auth_controller.dart';

/// Advisory crop-health check from a photo: Healthy, Needs attention, or a request for a clearer photo. Never a
/// diagnosis.
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
            'Photograph one crop or produce item, close up, in daylight (camera or gallery). You get the item, its '
            'category A, B or C with a health score, or a request for a clearer photo. A visual estimate, not a diagnosis.',
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

/// The farmer-facing decision sent by the server: healthy, needs_attention, retake_photo (no health claim, a clearer
/// photo is needed) or unavailable (the AI check could not run). The model's internal categories are never shown.
Map<String, dynamic>? cropHealthDecision(Map<String, dynamic> r) {
  final top = r.objOrNull('decision');
  if (top != null && top.str('status').isNotEmpty) return top;
  final nested = r.obj('features').objOrNull('analysis')?.objOrNull('decision');
  return nested != null && nested.str('status').isNotEmpty ? nested : null;
}

/// Short title for lists (history): the category when there is one, else the result's title.
String cropHealthTitle(Map<String, dynamic> r) {
  final d = cropHealthDecision(r);
  if (d == null) return 'Photo check';
  final category = d.strOrNull('health_category');
  final score = d['health_score'];
  if (category != null && score is num) return 'Category $category · ${score.round()}%';
  return d.str('title');
}

Color categoryColor(String? category, ColorScheme scheme) => switch (category) {
      'A' => const Color(0xFF2E7D32),
      'B' => const Color(0xFF1565C0),
      'C' => const Color(0xFFB26A00),
      _ => scheme.outline,
    };

/// The essential result only: the item, its parent category, the A/B/C health category with the health score, the
/// AI's confidence, one sentence of explanation and one next step. "Unable to classify" when the photo did not give
/// enough evidence. All texts come from the server in the farmer's language.
class CropHealthResult extends StatelessWidget {
  const CropHealthResult({super.key, required this.r});

  final Map<String, dynamic> r;

  @override
  Widget build(BuildContext context) {
    final d = cropHealthDecision(r);
    final theme = Theme.of(context);
    final small = theme.textTheme.bodySmall;
    if (d == null) {
      // only an old result cached on the phone before the server sent decisions
      return const SectionCard(title: 'Photo check', icon: Icons.eco_outlined, child: Text('Refresh to see this result.'));
    }
    final item = d.objOrNull('item');
    final category = d.strOrNull('health_category');
    final score = d['health_score'];
    final color = categoryColor(category, theme.colorScheme);
    final steps = d.strs('next_steps');
    final confidence = d.strOrNull('confidence_label') ?? d.strOrNull('confidence');
    return SectionCard(
      title: 'Photo check result',
      icon: Icons.eco_outlined,
      action: const DataKindChip('estimate'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (item != null) ...[
            Text(item.str('display_name'), style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
            if (item.strOrNull('parent_name') != null) Text(item.str('parent_name'), style: theme.textTheme.titleSmall),
            if (item.str('source') == 'photo') Text('Identified from the photo (AI estimate)', style: small),
            const SizedBox(height: 10),
          ],
          Semantics(
            container: true,
            excludeSemantics: true,
            label: category == null
                ? '${d.str('category_text')}. ${d.str('summary')}'
                : 'Category $category, ${d.str('category_text')}, health score ${score is num ? score.round() : ''} percent',
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.10),
                border: Border.all(color: color),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 26,
                    backgroundColor: color,
                    child: Text(
                      category ?? '?',
                      style: const TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w800),
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          category == null ? d.str('category_text') : 'Category $category · ${d.str('category_text')}',
                          style: theme.textTheme.titleMedium?.copyWith(color: color, fontWeight: FontWeight.w700),
                        ),
                        if (score is num)
                          Text('Health score ${score.toStringAsFixed(score == score.roundToDouble() ? 0 : 1)}%',
                              style: theme.textTheme.titleMedium,),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (confidence != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(
                children: [
                  Icon(Icons.speed, size: 18, color: theme.colorScheme.outline),
                  const SizedBox(width: 6),
                  Text('AI confidence: $confidence'),
                ],
              ),
            ),
          const SizedBox(height: 8),
          Text(d.str('summary')),
          if (steps.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('Next: ${steps.first}', style: const TextStyle(fontWeight: FontWeight.w600)),
          ],
          const SizedBox(height: 8),
          // what the score means, only next to a score; otherwise just that this is an estimate
          Text(
            score is num && d.strOrNull('score_meaning') != null
                ? d.str('score_meaning')
                : 'Visual estimate from one photo, not a diagnosis.',
            style: small,
          ),
        ],
      ),
    );
  }
}
