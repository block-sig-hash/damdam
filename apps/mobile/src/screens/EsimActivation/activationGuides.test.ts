import { activationGuideFor } from './activationGuides';

it.each([
  ['Tecno Camon 20', 'Tecno Camon / Spark'],
  ['TECNO SPARK 10', 'Tecno Camon / Spark'],
  ['Infinix Hot 40', 'Infinix Hot / Note'],
  ['Infinix Note 30', 'Infinix Hot / Note'],
  ['itel S23', 'itel'],
  ['Samsung Galaxy A54', 'Samsung Galaxy A-series'],
  ['Pixel 8', 'Android'],
])('AC-13.5: matches %s to %s', (model, expected) => {
  expect(activationGuideFor('android', model).name).toBe(expected);
});

it('AC-13.5: uses one stable iOS guide and identifies Android content as placeholder', () => {
  expect(activationGuideFor('ios', 'iPhone 15').contentStatus).toBe('production');
  expect(activationGuideFor('ios', 'iPhone SE').steps).toEqual(
    activationGuideFor('ios', 'iPhone 15').steps,
  );
  expect(activationGuideFor('android', 'Tecno Camon 20').contentStatus).toBe('placeholder');
});
