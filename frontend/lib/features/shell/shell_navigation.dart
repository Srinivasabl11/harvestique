import 'package:flutter_riverpod/flutter_riverpod.dart';

/// A tab the assistant asked the shell to open ("open Market" / "ಮಾರುಕಟ್ಟೆ ತೆರೆಯಿರಿ"). The shell switches and clears it.
/// Keys are the server's allowlist (`navigate_to`); unknown keys are ignored.
final shellTabRequestProvider = StateProvider<String?>((ref) => null);

const farmerTabs = {'home': 0, 'my_farm': 1, 'market': 2, 'harvest': 3, 'reminders': 4};
const buyerTabs = {'home': 0, 'market': 0, 'demands': 1, 'orders': 2, 'reminders': 3};
