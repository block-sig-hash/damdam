export interface ActivationGuideStep {
  instruction: string;
  screenshotLabel: string;
}

export interface ActivationGuide {
  name: string;
  contentStatus: 'production' | 'placeholder';
  steps: ActivationGuideStep[];
}

const genericAndroidSteps: ActivationGuideStep[] = [
  { instruction: 'Open Settings.', screenshotLabel: 'Settings home' },
  { instruction: 'Open SIM cards, Mobile network, or Connections.', screenshotLabel: 'SIM settings' },
  { instruction: 'Select the DamDam eSIM and turn it on.', screenshotLabel: 'DamDam eSIM switch' },
  { instruction: 'Choose DamDam for mobile data.', screenshotLabel: 'Mobile data selection' },
];

const families: Array<{ pattern: RegExp; name: string }> = [
  { pattern: /tecno.*(camon|spark)/i, name: 'Tecno Camon / Spark' },
  { pattern: /infinix.*(hot|note)/i, name: 'Infinix Hot / Note' },
  { pattern: /itel/i, name: 'itel' },
  { pattern: /samsung.*(galaxy\s*)?a/i, name: 'Samsung Galaxy A-series' },
];

export function activationGuideFor(platform: 'ios' | 'android', deviceModel: string): ActivationGuide {
  if (platform === 'ios') {
    return {
      name: 'iPhone',
      contentStatus: 'production',
      steps: [
        { instruction: 'Open Settings, then Cellular.', screenshotLabel: 'Settings → Cellular' },
        { instruction: 'Tap Add eSIM.', screenshotLabel: 'Add eSIM' },
        { instruction: 'Choose Use QR Code.', screenshotLabel: 'Use QR Code' },
        { instruction: 'Scan the DamDam QR code shown in the app.', screenshotLabel: 'Scan QR code' },
        { instruction: 'Turn on the new line for Cellular Data.', screenshotLabel: 'Cellular Data selection' },
      ],
    };
  }
  const family = families.find(candidate => candidate.pattern.test(deviceModel));
  return {
    name: family?.name ?? 'Android',
    contentStatus: 'placeholder',
    steps: genericAndroidSteps,
  };
}
