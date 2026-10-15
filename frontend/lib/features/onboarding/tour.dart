import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/util/json.dart';
import '../auth/auth_controller.dart';

/// Raise this when a major feature should be introduced to everyone again: each account stores the highest
/// version it finished or skipped (server side), so the tour shows once per version, on any phone.
const kTourVersion = 1;

class TourStep {
  const TourStep(this.icon, this.title, this.body);

  final IconData icon;
  final String title;
  final String body;
}

const farmerTour = <TourStep>[
  TourStep(
    Icons.waving_hand_outlined,
    'Welcome to Harvestique',
    'A quick look at what you can do. It takes about a minute. You can skip it and open it again from Account > Help & guide.',
  ),
  TourStep(
    Icons.agriculture_outlined,
    'Your farm and plots',
    'Open My Farm and tap "Add farm". Then add your plots (fields) with their size. Add the farm location to get weather.',
  ),
  TourStep(
    Icons.spa_outlined,
    'Your crops',
    'On a plot, tap "Add crop", choose the crop, its sowing date and area. Your crops are listed under the farm in Crops.',
  ),
  TourStep(
    Icons.wb_cloudy_outlined,
    'Weather',
    'The Home screen shows the weather for your farm: temperature, rain chance and the coming days. It is a forecast, not a promise.',
  ),
  TourStep(
    Icons.calculate_outlined,
    'Income planner',
    'My Farm > Income plans: add the crops you plan to grow with expected yield, price and costs. You see the estimated income range.',
  ),
  TourStep(
    Icons.receipt_long_outlined,
    'Expenses',
    'Record what you spend on seed, fertilizer, labour and more from the farm or crop page. The total is always up to date.',
  ),
  TourStep(
    Icons.visibility_outlined,
    'Observations and crop health',
    'On a crop, add what you see in the field. "Crop health" checks a photo of leaves and gives a suggestion, never a diagnosis.',
  ),
  TourStep(
    Icons.scale_outlined,
    'Harvest',
    'When you harvest, record the weighed quantity on the crop. The Harvest tab shows what you can offer to buyers.',
  ),
  TourStep(
    Icons.alarm_outlined,
    'Reminders',
    'The Reminders tab keeps your tasks: watering, spraying, harvest. Add, edit, move or delete them. Due reminders appear under the bell.',
  ),
  TourStep(
    Icons.storefront_outlined,
    'Orders',
    'When a buyer orders from your crop, the Market tab asks you to accept or decline. After accepting, mark it "preparing" and "ready".',
  ),
  TourStep(
    Icons.mic_none,
    'Ask Harvestique',
    'Tap "Ask" and hold the microphone while you speak, in English or Kannada. Ask about your expenses, weather, plans, or anything else.',
  ),
];

const buyerTour = <TourStep>[
  TourStep(
    Icons.waving_hand_outlined,
    'Welcome to Harvestique',
    'A quick look at buying from farmers. You can skip it and open it again from Account > Help & guide.',
  ),
  TourStep(
    Icons.storefront_outlined,
    'Market',
    'See the produce farmers expect to harvest. Quantities are cautious estimates from their predictions, not guarantees.',
  ),
  TourStep(
    Icons.search,
    'Search and filters',
    'Search by crop, quantity, delivery dates and minimum grade to see which farms could supply you.',
  ),
  TourStep(
    Icons.request_quote_outlined,
    'Demands and details',
    'In Demands, describe what you need. Harvestique ranks matching farms and can pool several farms to fill your quantity.',
  ),
  TourStep(
    Icons.shopping_cart_checkout,
    'Booking an order',
    'Open a pool and place your order. Each farmer is asked to accept; you are told when they accept, prepare and are ready.',
  ),
  TourStep(
    Icons.receipt_long_outlined,
    'Order status',
    'The Orders tab shows every order with its ID and status, the farms supplying it, delivered quantities and the full trace.',
  ),
  TourStep(
    Icons.notifications_outlined,
    'Notifications',
    'The bell shows order updates and reminders. Tap "Mark as read" on each one, or "Mark all read".',
  ),
  TourStep(
    Icons.account_circle_outlined,
    'Your account',
    'The account menu (top right) has Help & guide, the server status and Sign out.',
  ),
];

List<TourStep> tourFor(String role) => switch (role) {
      'farmer' => farmerTour,
      'buyer' => buyerTour,
      _ => const <TourStep>[],
    };

/// The guided tour. Pops with true when finished or skipped.
class TourScreen extends StatefulWidget {
  const TourScreen({super.key, required this.steps});

  final List<TourStep> steps;

  @override
  State<TourScreen> createState() => _TourScreenState();
}

class _TourScreenState extends State<TourScreen> {
  final _pages = PageController();
  int _i = 0;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _go(int i) => _pages.animateToPage(i, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);

  @override
  Widget build(BuildContext context) {
    final last = _i == widget.steps.length - 1;
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: Text('Guide ${_i + 1} of ${widget.steps.length}'),
        actions: [if (!last) TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Skip'))],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: PageView(
                controller: _pages,
                onPageChanged: (i) => setState(() => _i = i),
                children: [
                  for (final s in widget.steps)
                    SingleChildScrollView(
                      padding: const EdgeInsets.all(28),
                      child: Semantics(
                        container: true,
                        label: '${s.title}. ${s.body}',
                        child: Column(
                          children: [
                            const SizedBox(height: 24),
                            Icon(s.icon, size: 88, color: scheme.primary),
                            const SizedBox(height: 24),
                            Text(s.title, textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineSmall),
                            const SizedBox(height: 16),
                            Text(s.body, textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleMedium),
                          ],
                        ),
                      ),
                    ),
                ],
              ),
            ),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                for (var k = 0; k < widget.steps.length; k++)
                  Container(
                    width: k == _i ? 18 : 8,
                    height: 8,
                    margin: const EdgeInsets.all(3),
                    decoration: BoxDecoration(
                      color: k == _i ? scheme.primary : scheme.outlineVariant,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton(onPressed: _i == 0 ? null : () => _go(_i - 1), child: const Text('Back')),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton(
                      onPressed: last ? () => Navigator.pop(context, true) : () => _go(_i + 1),
                      child: Text(last ? 'Finish' : 'Next'),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Opens the tour for [role] and records it as seen for this account (finished or skipped).
Future<void> showTour(BuildContext context, WidgetRef ref, String role) async {
  final steps = tourFor(role);
  if (steps.isEmpty) return;
  await Navigator.of(context)
      .push<bool>(MaterialPageRoute<bool>(fullscreenDialog: true, builder: (_) => TourScreen(steps: steps)));
  try {
    await ref.read(authProvider.notifier).markTourSeen(kTourVersion);
  } catch (_) {
    // offline: it simply shows again after the next sign-in; nothing else depends on it
  }
}

/// Shows the tour once, after the first sign-in on this account (any phone), for farmers and buyers.
class TourGate extends ConsumerStatefulWidget {
  const TourGate({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<TourGate> createState() => _TourGateState();
}

class _TourGateState extends ConsumerState<TourGate> {
  // accounts that already got the tour in this app session (even if saving "seen" failed while offline)
  static final _shownThisRun = <String>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeShow(ref.read(authProvider)));
  }

  void _maybeShow(AuthState auth) {
    if (!mounted || auth.status != AuthStatus.signedIn) return;
    final id = auth.user.str('id');
    if (_shownThisRun.contains(id)) return;
    if (auth.user.intVal('tour_version_seen') >= kTourVersion || tourFor(auth.role).isEmpty) return;
    _shownThisRun.add(id);
    showTour(context, ref, auth.role);
  }

  @override
  Widget build(BuildContext context) {
    // the session may still be restoring when this screen first appears
    ref.listen<AuthState>(authProvider, (prev, next) {
      if (prev?.status != AuthStatus.signedIn && next.status == AuthStatus.signedIn) _maybeShow(next);
    });
    return widget.child;
  }
}
