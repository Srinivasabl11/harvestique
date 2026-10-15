import 'package:flutter/material.dart';

import '../errors/app_failure.dart';
import '../network/api_client.dart';

/// Asks before something is removed. True only when the person confirms.
Future<bool> confirmAction(
  BuildContext context, {
  required String title,
  required String message,
  String confirm = 'Delete',
  String keep = 'Keep',
}) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: Text(keep)),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(confirm)),
        ],
      ),
    ) ==
    true;

void showMessage(BuildContext context, String text, {Future<void> Function()? retry}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Text(text),
        duration: Duration(seconds: retry == null ? 4 : 6),
        action: retry == null ? null : SnackBarAction(label: 'Retry', onPressed: retry),
      ),
    );
}

/// Outcome of [deleteOrFallback].
enum RemoveResult { deleted, fallback, cancelled, failed }

/// Deletes a record after confirmation. When the server refuses because the record still has history (one of
/// [historyCodes]), it explains why and offers [fallback] instead (archive / mark abandoned), never deleting history.
Future<RemoveResult> deleteOrFallback(
  BuildContext context, {
  required String what,
  required Future<void> Function() delete,
  required Set<String> historyCodes,
  String? fallbackLabel,
  Future<void> Function()? fallback,
}) async {
  if (!await confirmAction(context, title: 'Delete $what?', message: 'This cannot be undone.')) {
    return RemoveResult.cancelled;
  }
  try {
    await delete();
    if (context.mounted) showMessage(context, '${what[0].toUpperCase()}${what.substring(1)} deleted');
    return RemoveResult.deleted;
  } catch (e) {
    final f = e is AppFailure ? e : mapDioError(e);
    if (!context.mounted) return RemoveResult.failed;
    if (historyCodes.contains(f.code) && fallback != null && fallbackLabel != null) {
      final ok = await confirmAction(
        context,
        title: 'Keep the history',
        message: '${f.message}\n\n$fallbackLabel keeps the records but removes it from your active lists.',
        confirm: fallbackLabel,
        keep: 'Cancel',
      );
      if (!ok || !context.mounted) return RemoveResult.cancelled;
      try {
        await fallback();
        if (context.mounted) showMessage(context, 'Done: $fallbackLabel');
        return RemoveResult.fallback;
      } catch (e2) {
        if (context.mounted) showMessage(context, (e2 is AppFailure ? e2 : mapDioError(e2)).message);
        return RemoveResult.failed;
      }
    }
    showMessage(context, f.message);
    return RemoveResult.failed;
  }
}
