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
            'Take a clear, close photo of the leaves in daylight. You get Healthy or Needs attention with what to check '
            'next, or a request for a clearer photo. It is a suggestion, not a diagnosis.',
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

/// Short title for lists (history), in the language the result was made in.
String cropHealthTitle(Map<String, dynamic> r) => cropHealthDecision(r)?.str('title') ?? 'Photo check';

(IconData, Color) cropHealthStyle(String status, ColorScheme scheme) => switch (status) {
      'healthy' => (Icons.check_circle, const Color(0xFF2E7D32)),
      'needs_attention' => (Icons.warning_amber_rounded, const Color(0xFFB26A00)),
      'retake_photo' => (Icons.add_a_photo_outlined, scheme.primary),
      _ => (Icons.cloud_off_outlined, scheme.outline),
    };

class CropHealthResult extends StatelessWidget {
  const CropHealthResult({super.key, required this.r});

  final Map<String, dynamic> r;

  @override
  Widget build(BuildContext context) {
    final decision = cropHealthDecision(r);
    final analysis = r.obj('features').objOrNull('analysis');
    final theme = Theme.of(context);
    final small = theme.textTheme.bodySmall;
    if (decision == null) {
      // only an old result cached on the phone before the server sent decisions: no category is shown
      return SectionCard(
        title: 'Photo check',
        icon: Icons.eco_outlined,
        child: Text('Refresh to see this result. ${r.str('disclaimer')}'),
      );
    }
    final status = decision.str('status');
    final (icon, color) = cropHealthStyle(status, theme.colorScheme);
    final signs = decision.strs('signs');
    final showScore = status == 'healthy' || status == 'needs_attention';
    return SectionCard(
      title: 'Photo check result',
      icon: Icons.eco_outlined,
      action: const DataKindChip('estimate'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            container: true,
            label: 'Result: ${decision.str('title')}. ${decision.str('summary')}',
            excludeSemantics: true,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.10),
                border: Border.all(color: color),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(icon, color: color, size: 32),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(decision.str('title'),
                            style: theme.textTheme.titleLarge?.copyWith(color: color, fontWeight: FontWeight.w700),),
                        const SizedBox(height: 4),
                        Text(decision.str('summary')),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (decision.strOrNull('confidence_text') != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(decision.str('confidence_text'), style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
          if (signs.isNotEmpty) ...[
            const SizedBox(height: 4),
            for (final s in signs) Text('• $s'),
          ],
          if (analysis != null && showScore) ...[
            const SizedBox(height: 8),
            ConditionScore(condition: analysis.obj('condition')),
          ],
          // "What is visible" repeats the signs listed above, so it is shown only when there are none
          if (analysis != null)
            ...[
              for (final s in analysis.objs('sections'))
                if (s.str('id') != 'observations' || signs.isEmpty) ReportSection(section: s),
            ]
          else ...[
            const SizedBox(height: 8),
            for (final step in decision.strs('next_steps')) Text('• $step'),
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
