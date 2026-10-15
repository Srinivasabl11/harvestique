import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_controller.dart';
import '../onboarding/tour.dart';

class ManualSection {
  const ManualSection(this.icon, this.title, this.points);

  final IconData icon;
  final String title;
  final List<String> points;

  bool matches(String q) => q.isEmpty || title.toLowerCase().contains(q) || points.any((p) => p.toLowerCase().contains(q));
}

const _account = ManualSection(Icons.lock_outline, 'Account, password and sign-in', [
  'Signing in has two steps: your mobile number and password, then a one-time code sent to your phone by SMS.',
  'Forgot your password? On the sign-in screen tap "Forgot password?", enter your number, then the code and a new password. All devices are signed out.',
  'On a test server without an SMS service, the code is shown in a box marked "DEVELOPMENT MODE – not sent by SMS". A real server sends it by SMS.',
  'Account menu (top right): Help & guide, assistant language (farmers), server status and Sign out.',
]);

const _assistant = ManualSection(Icons.mic_none, 'Ask Harvestique (voice assistant)', [
  'Tap "Ask". Press and hold the big microphone while you speak, then let go. Slide your finger up to cancel.',
  'You can also type your question.',
  'Questions about your own records (expenses, weather for your farm, plans, reminders, harvest) are answered from your data.',
  'General questions (crop care, how things work, everyday questions) are answered by a local AI model and marked "AI (general)". They can be wrong: check with an agriculture officer.',
  'Saving something (an expense, a reminder) always asks you to confirm first.',
  'Speech uses your phone\'s own speech engines. English (India) and Kannada work only if they are installed on the phone (Settings > Languages / Text-to-speech). The local AI writes general answers in English.',
]);

const _notifications = ManualSection(Icons.notifications_outlined, 'Notifications and reminders', [
  'The bell shows how many notifications are unread. Open it and tap "Mark as read" on one, or "Mark all read".',
  'Reminders tab: "New reminder" sets what, when and how often. Tap ⋮ on a reminder to edit, move or delete it; tap ✓ when it is done.',
  'A reminder cannot be set in the past. Repeating reminders move to their next time when you mark them done.',
  'Notifications appear inside the app (no SMS or push messages are sent).',
]);

const farmerManual = <ManualSection>[
  ManualSection(Icons.flag_outlined, 'Getting started', [
    '1. My Farm > "Add farm": name, size in acres and, for weather, the location.',
    '2. Open the farm > Plots > + : add each field with its size.',
    '3. On a plot tap "Add crop": the crop, sowing date and area.',
    '4. Record expenses and observations as the season goes on.',
  ]),
  ManualSection(Icons.agriculture_outlined, 'Farms and plots', [
    'Open a farm and tap ⋮ next to its name to edit it (also its location), archive it or delete it.',
    'Tap ⋮ on a plot to edit or delete it.',
    'Farms or plots that already have records cannot be deleted; you are offered "Archive" instead, so your history is kept.',
    'Turn on "Show archived farms" in My Farm to see and restore archived farms.',
  ]),
  ManualSection(Icons.spa_outlined, 'Crops', [
    'Add a crop from a plot. All crops of the farm are listed under Crops on the farm page.',
    'When adding a crop, search by English or Kannada name, or tap a category (vegetables, fruits, fodder, medicinal and more). Durations are indicative; change the expected harvest date if yours differs.',
    'Open a crop and tap ⋮ to edit its details, mark it abandoned (crop failed or removed) or delete it.',
    'A crop that has expenses or observations cannot be deleted: mark it abandoned instead.',
  ]),
  ManualSection(Icons.wb_cloudy_outlined, 'Weather', [
    'The Home screen shows the current temperature, whether rain is likely, and the coming days for your farm.',
    'Weather needs the farm location: open the farm > ⋮ > Edit farm > latitude and longitude.',
    'Forecasts are model estimates from Open-Meteo (free). They are not guarantees, and "raining now" is a model estimate, not a rain gauge.',
  ]),
  ManualSection(Icons.receipt_long_outlined, 'Expenses', [
    'On a farm (Expenses) or a crop (Expenses > Open), tap "Add expense".',
    'Tap an expense to change it; tap the bin to delete it.',
    'You can also say "I spent 500 rupees on fertilizer today" to the assistant and confirm.',
  ]),
  ManualSection(Icons.task_alt, 'Field work log', [
    'Open a farm > "Field work log", or a crop > Field work > Open, then "Add field work".',
    'Choose the work (irrigation, weeding, pest control…), the date and optionally the crop.',
    'Tap an entry to change it; tap the bin to delete it. For work you plan to do later, use a reminder.',
  ]),
  ManualSection(Icons.calculate_outlined, 'Income planner', [
    'My Farm > Income plans > "New plan", then "Add crop" with your expected yield, price and costs.',
    'Or add a crop from its harvest prediction.',
    'The plan shows estimated income as a low / expected / high range, next to the expenses you actually recorded.',
  ]),
  ManualSection(Icons.visibility_outlined, 'Observations and crop health', [
    'On a crop, "Field observations > Add": how the crop looks, growth stage and any loss. Tap one to edit or delete it.',
    'Crop health: take a clear, close photo of the affected leaves in daylight. The result is a suggestion with its uncertainty, never a diagnosis.',
    'The check runs on the Harvestique server with a free local AI model and can take up to a minute or two. It describes the signs it sees (spots, yellowing, curling); it can be wrong.',
    'A whole-field photo, a blurry photo or a photo that is not a plant gets "unclear": move closer to the leaves and try again.',
    'If the AI model is not running, only a colour check is done and no health label is given.',
  ]),
  ManualSection(Icons.scale_outlined, 'Harvest', [
    'When you harvest, mark the crop harvested and record the weighed quantity.',
    'If you typed a wrong quantity, the crop page ⋮ > "Correct recorded harvest" fixes it, but only before any of it reaches a collection hub.',
    'The Harvest tab shows your expected stock and lets you offer it to buyers.',
  ]),
  ManualSection(Icons.storefront_outlined, 'Market and orders', [
    'Market tab: buyer requests for your crops. Accept or decline each one.',
    'After accepting, use "Mark preparing" and then "Mark ready". The buyer is told each time.',
    'Each order has an ID like #1A2B3C4D, shown in the app and in notifications.',
  ]),
  _notifications,
  _assistant,
  _account,
];

const buyerManual = <ManualSection>[
  ManualSection(Icons.flag_outlined, 'Getting started', [
    '1. Market: see what farmers expect to harvest.',
    '2. Demands: describe what you need (crop, quantity, dates, minimum grade).',
    '3. Open the demand, create a pool from the matching farms, and place your order.',
  ]),
  ManualSection(Icons.search, 'Market and search', [
    'Search by crop, quantity, delivery dates and minimum grade.',
    'Demands tab: open a demand that has no harvest pool yet and tap "Withdraw this demand" if you no longer need it.',
    'Quantities are cautious estimates from farmers\' predictions, not guarantees.',
  ]),
  ManualSection(Icons.shopping_cart_checkout, 'Orders', [
    'Orders tab: every order with its ID, status and delivered quantity.',
    'Each farm is asked to accept. You are notified when farms accept, decline, prepare and are ready.',
    'You can cancel an order before produce is received. "Trace" shows where your produce came from.',
  ]),
  _notifications,
  _account,
];

List<ManualSection> manualFor(String role) => role == 'farmer' ? farmerManual : buyerManual;

/// Help & guide: the user manual for this role, searchable, and the guided tour.
class HelpScreen extends ConsumerStatefulWidget {
  const HelpScreen({super.key});

  @override
  ConsumerState<HelpScreen> createState() => _HelpScreenState();
}

class _HelpScreenState extends ConsumerState<HelpScreen> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final role = ref.watch(authProvider).role;
    final sections = manualFor(role).where((s) => s.matches(_q)).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Help & guide')),
      body: ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          if (tourFor(role).isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
              child: FilledButton.icon(
                onPressed: () => showTour(context, ref, role),
                icon: const Icon(Icons.play_circle_outline),
                label: const Text('Start the guided tour'),
              ),
            ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search the guide, e.g. "expense"'),
              onChanged: (v) => setState(() => _q = v.trim().toLowerCase()),
            ),
          ),
          if (sections.isEmpty) const Padding(padding: EdgeInsets.all(16), child: Text('Nothing matches. Try another word.')),
          for (final s in sections)
            ExpansionTile(
              leading: Icon(s.icon),
              title: Text(s.title),
              initiallyExpanded: _q.isNotEmpty,
              childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              children: [
                for (final p in s.points)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [const Text('•  '), Expanded(child: Text(p))],
                    ),
                  ),
              ],
            ),
        ],
      ),
    );
  }
}
