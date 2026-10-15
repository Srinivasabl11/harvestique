import 'package:flutter/material.dart';

import '../errors/app_failure.dart';
import '../network/api_client.dart';
import '../theme/app_theme.dart';
import '../util/format.dart';

/// Shows a Future-backed read with loading, error (with retry), empty and offline-cached states.
class LoadedView<T> extends StatelessWidget {
  const LoadedView({
    super.key,
    required this.future,
    required this.builder,
    this.onRetry,
    this.isEmpty,
    this.emptyMessage = 'Nothing here yet.',
    this.header,
  });

  final AsyncSnapshot<Loaded<T>> future;
  final Widget Function(BuildContext context, T data) builder;
  final VoidCallback? onRetry;
  final bool Function(T data)? isEmpty;
  final String emptyMessage;

  /// Shown above the loading, error and empty panels, so content that needs no data stays visible
  /// while the server is slow or unreachable. A [builder] that uses it places it in its own list.
  final Widget? header;

  Widget _withHeader(Widget panel) => header == null ? panel : ListView(children: [header!, panel]);

  @override
  Widget build(BuildContext context) {
    final snap = future;
    if (snap.hasError) {
      return _withHeader(ErrorPanel(error: snap.error!, onRetry: onRetry));
    }
    if (!snap.hasData) {
      return _withHeader(
        const Center(
          child: Padding(
            padding: EdgeInsets.all(32),
            child: CircularProgressIndicator(semanticsLabel: 'Loading'),
          ),
        ),
      );
    }
    final loaded = snap.data!;
    final body = (isEmpty?.call(loaded.data) ?? false)
        ? _withHeader(EmptyPanel(message: emptyMessage))
        : builder(context, loaded.data);
    if (!loaded.isCached) return body;
    return Column(
      children: [
        OfflineBanner(savedAt: loaded.cachedAt!),
        Expanded(child: body),
      ],
    );
  }
}

class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, required this.savedAt});

  final DateTime savedAt;

  @override
  Widget build(BuildContext context) {
    return MaterialBanner(
      leading: const Icon(Icons.cloud_off),
      content: Text(
        'Offline: showing data saved on ${dateTime(savedAt.toIso8601String())}. It may be out of date.',
      ),
      actions: const [SizedBox.shrink()],
    );
  }
}

class ErrorPanel extends StatelessWidget {
  const ErrorPanel({super.key, required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final f = error is AppFailure ? error as AppFailure : mapDioError(error);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(f.isOffline ? Icons.wifi_off : Icons.error_outline, size: 48),
            const SizedBox(height: 12),
            Text(f.message, textAlign: TextAlign.center),
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Try again'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class EmptyPanel extends StatelessWidget {
  const EmptyPanel({
    super.key,
    required this.message,
    this.icon = Icons.inbox_outlined,
  });

  final String message;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

/// Where a number comes from: measured, estimate, assumption, simulated, user entered.
class DataKindChip extends StatelessWidget {
  const DataKindChip(this.kind, {super.key});

  final String kind;

  static (Color, String) style(String kind) => switch (kind) {
        'measured' => (Signal.measured, 'Measured'),
        'actual' => (Signal.measured, 'Actual (recorded)'),
        'ai_general' => (Signal.assumption, 'AI (general, not your data)'),
        'estimate' => (Signal.estimate, 'Estimate'),
        'assumption' => (Signal.assumption, 'Assumption'),
        'simulated' => (Signal.simulated, 'Simulated'),
        'user_entered' => (Signal.userEntered, 'Entered by you'),
        'scheduled' => (Signal.userEntered, 'Scheduled'),
        'pending' => (Signal.assumption, 'Pending'),
        _ => (Signal.assumption, label(kind)),
      };

  @override
  Widget build(BuildContext context) {
    final (color, text) = style(kind);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

Color levelColor(String level) => switch (level) {
      'low' => Signal.low,
      'medium' => Signal.medium,
      'high' => Signal.high,
      _ => Signal.assumption,
    };

/// Confidence of an estimate (0-100). Always says it is not a guarantee.
class ConfidenceBadge extends StatelessWidget {
  const ConfidenceBadge({
    super.key,
    required this.score,
    required this.level,
    this.basis,
  });

  final double score;
  final String level;
  final String? basis;

  @override
  Widget build(BuildContext context) {
    final good = level == 'high' ? Signal.low : (level == 'low' ? Signal.high : Signal.medium);
    return Semantics(
      label: 'Confidence ${number(score)} out of 100, $level',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.verified_outlined, size: 18),
              const SizedBox(width: 6),
              Text(
                'Confidence ${number(score)}/100 · ${label(level)}',
                style: TextStyle(color: good, fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const SizedBox(height: 4),
          LinearProgressIndicator(
            value: (score / 100).clamp(0, 1),
            color: good,
            minHeight: 6,
          ),
          if (basis != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                basis == 'calibrated'
                    ? 'Backed by recorded harvests.'
                    : 'Rule-based estimate, not a measured accuracy.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
        ],
      ),
    );
  }
}

class RiskChip extends StatelessWidget {
  const RiskChip({super.key, required this.level, this.score});

  final String level;
  final double? score;

  @override
  Widget build(BuildContext context) {
    final c = levelColor(level);
    final text = level == 'insufficient_data'
        ? 'Risk: not enough data'
        : 'Risk: ${label(level)}${score == null ? '' : ' (${number(score)})'}';
    return Chip(
      avatar: Icon(Icons.warning_amber_rounded, color: c, size: 18),
      label: Text(text),
      side: BorderSide(color: c),
    );
  }
}

class SectionCard extends StatelessWidget {
  const SectionCard({
    super.key,
    required this.title,
    required this.child,
    this.action,
    this.icon,
  });

  final String title;
  final Widget child;
  final Widget? action;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (icon != null) ...[Icon(icon), const SizedBox(width: 8)],
                Expanded(
                  child: Text(
                    title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                if (action != null) action!,
              ],
            ),
            const SizedBox(height: 8),
            child,
          ],
        ),
      ),
    );
  }
}

class KeyValue extends StatelessWidget {
  const KeyValue(this.k, this.v, {super.key, this.kind});

  final String k;
  final String v;
  final String? kind;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            child: Text(k, style: Theme.of(context).textTheme.bodyMedium),
          ),
          Flexible(
            child: Text(
              v,
              textAlign: TextAlign.end,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
          if (kind != null) ...[const SizedBox(width: 8), DataKindChip(kind!)],
        ],
      ),
    );
  }
}

/// Runs an action with a progress dialog-free pattern: shows the server's message on failure.
Future<bool> runAction(
  BuildContext context,
  Future<void> Function() action, {
  String? success,
}) async {
  final messenger = ScaffoldMessenger.of(context);
  try {
    await action();
    if (success != null) {
      messenger
        ..hideCurrentSnackBar() // show the newest result now, not after older messages time out
        ..showSnackBar(SnackBar(content: Text(success)));
    }
    return true;
  } catch (e) {
    final f = e is AppFailure ? e : mapDioError(e);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(
        content: Text(f.message),
        duration: const Duration(seconds: 5),
      ),
    );
    return false;
  }
}

/// Text field with sensible defaults for forms.
class FormText extends StatelessWidget {
  const FormText({
    super.key,
    required this.controller,
    required this.label,
    this.keyboard,
    this.validator,
    this.hint,
    this.obscure = false,
  });

  final TextEditingController controller;
  final String label;
  final TextInputType? keyboard;
  final String? Function(String?)? validator;
  final String? hint;
  final bool obscure;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: TextFormField(
        controller: controller,
        keyboardType: keyboard,
        obscureText: obscure,
        validator: validator,
        decoration: InputDecoration(labelText: label, hintText: hint),
      ),
    );
  }
}

String? requiredText(String? v) => (v == null || v.trim().isEmpty) ? 'Required' : null;

String? positiveNumber(String? v) {
  final n = double.tryParse((v ?? '').trim());
  return (n == null || n <= 0) ? 'Enter a number greater than 0' : null;
}

String? optionalNumber(String? v) {
  if (v == null || v.trim().isEmpty) return null;
  return double.tryParse(v.trim()) == null ? 'Enter a number' : null;
}

/// Picks a date with the platform date picker.
Future<DateTime?> pickDate(BuildContext context, DateTime initial) {
  return showDatePicker(
    context: context,
    initialDate: initial,
    firstDate: DateTime(2020),
    lastDate: DateTime(2035),
  );
}

/// Loads data, shows every state (loading, error with retry, empty, offline copy) and supports pull-to-refresh.
/// `builder` should return a scrollable (e.g. ListView) so pull-to-refresh works.
class Reloadable<T> extends StatefulWidget {
  const Reloadable({
    super.key,
    required this.load,
    required this.builder,
    this.isEmpty,
    this.emptyMessage = 'Nothing here yet.',
    this.header,
  });

  final Future<Loaded<T>> Function() load;
  final Widget Function(
    BuildContext context,
    T data,
    Future<void> Function() reload,
  ) builder;
  final bool Function(T data)? isEmpty;
  final String emptyMessage;

  /// See [LoadedView.header].
  final Widget? header;

  @override
  State<Reloadable<T>> createState() => _ReloadableState<T>();
}

class _ReloadableState<T> extends State<Reloadable<T>> {
  late Future<Loaded<T>> _future = widget.load();

  Future<void> _reload() async {
    final next = widget.load();
    // a block body: an arrow returning the Future makes setState throw in debug builds (no rebuild at all)
    setState(() {
      _future = next;
    });
    try {
      await next;
    } catch (_) {
      // shown by the error panel
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Loaded<T>>(
      future: _future,
      builder: (context, snap) => LoadedView<T>(
        future: snap,
        onRetry: _reload,
        isEmpty: widget.isEmpty,
        emptyMessage: widget.emptyMessage,
        header: widget.header,
        builder: (context, data) => RefreshIndicator(
          onRefresh: _reload,
          child: widget.builder(context, data, _reload),
        ),
      ),
    );
  }
}

/// Wraps a live-only read (no offline copy) as a Loaded value.
Future<Loaded<T>> live<T>(Future<T> f) async => Loaded(await f);
