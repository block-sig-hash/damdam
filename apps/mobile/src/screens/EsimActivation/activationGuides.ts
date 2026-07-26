export interface ActivationGuideStep {
  instruction: string;
  screenshotLabel: string;
}

export interface ActivationGuide {
  name: string;
  contentStatus: 'production' | 'placeholder';
  steps: ActivationGuideStep[];
}

function genericAndroidSteps(): ActivationGuideStep[] {
  return [
    { instruction: i18n.t('guide.android.openSettings', {ns: 'esim'}), screenshotLabel: i18n.t('guide.android.settingsHome', {ns: 'esim'}) },
    { instruction: i18n.t('guide.android.openSim', {ns: 'esim'}), screenshotLabel: i18n.t('guide.android.simSettings', {ns: 'esim'}) },
    { instruction: i18n.t('guide.android.enable', {ns: 'esim'}), screenshotLabel: i18n.t('guide.android.switch', {ns: 'esim'}) },
    { instruction: i18n.t('guide.android.chooseData', {ns: 'esim'}), screenshotLabel: i18n.t('guide.android.dataSelection', {ns: 'esim'}) },
  ];
}

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
        { instruction: i18n.t('guide.ios.openCellular', {ns: 'esim'}), screenshotLabel: i18n.t('guide.ios.cellularSettings', {ns: 'esim'}) },
        { instruction: i18n.t('guide.ios.addEsim', {ns: 'esim'}), screenshotLabel: i18n.t('guide.ios.addEsimLabel', {ns: 'esim'}) },
        { instruction: i18n.t('guide.ios.chooseQr', {ns: 'esim'}), screenshotLabel: i18n.t('guide.ios.chooseQrLabel', {ns: 'esim'}) },
        { instruction: i18n.t('guide.ios.scanQr', {ns: 'esim'}), screenshotLabel: i18n.t('guide.ios.scanQrLabel', {ns: 'esim'}) },
        { instruction: i18n.t('guide.ios.enableData', {ns: 'esim'}), screenshotLabel: i18n.t('guide.ios.dataSelection', {ns: 'esim'}) },
      ],
    };
  }
  const family = families.find(candidate => candidate.pattern.test(deviceModel));
  return {
    name: family?.name ?? i18n.t('guide.android.genericDevice', {ns: 'esim'}),
    contentStatus: 'placeholder',
    steps: genericAndroidSteps(),
  };
}
import {i18n} from '../../i18n';
