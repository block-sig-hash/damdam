import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import type { Receipt, SupportCategory, SupportRequest } from '../../api/accountClient';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';

interface SupportScreenProps {
  requests: SupportRequest[];
  /** Offered as attachments. The customer picks what it is about. */
  receipts: Receipt[];
  busy: boolean;
  errorMessage: string | null;
  lastReference: string | null;
  onSubmit: (input: {
    category: SupportCategory;
    subject: string;
    body: string;
    orderId?: string;
  }) => void;
  onBack: () => void;
}

const CATEGORIES: SupportCategory[] = [
  'installation',
  'connectivity',
  'billing',
  'refund',
  'account',
  'other',
];

/**
 * Get help (US-38, chunk 21).
 *
 * The order picker is the point of the screen. A ticket that says "I was charged
 * twice" with no reference costs a round trip before anybody can start, and the
 * customer has been looking at the order the whole time — so attaching it is one
 * tap here rather than a question later.
 *
 * The reference is shown after sending and kept in the list. Somebody phoning in
 * needs to be able to read it out, and a ticket they cannot name is one they
 * describe again from the beginning.
 */
export function SupportScreen({
  requests,
  receipts,
  busy,
  errorMessage,
  lastReference,
  onSubmit,
  onBack,
}: SupportScreenProps) {
  const { t } = useTranslation('account');
  const [category, setCategory] = useState<SupportCategory>('other');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [orderId, setOrderId] = useState<string | undefined>(undefined);

  const canSubmit = subject.trim().length > 0 && body.trim().length > 0 && !busy;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      testID="support-screen"
    >
      <Text style={styles.title} accessibilityRole="header">
        {t('sections.support')}
      </Text>
      <Text style={styles.body}>{t('support.intro')}</Text>

      {errorMessage ? (
        <Text style={styles.error} accessibilityRole="alert">
          {errorMessage}
        </Text>
      ) : null}

      {lastReference ? (
        <Text style={styles.sent} accessibilityRole="alert" testID="support-sent">
          {t('support.sent', { reference: lastReference })}
        </Text>
      ) : null}

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('support.category')}</Text>
        {CATEGORIES.map(option => (
          <SecondaryButton
            key={option}
            label={t(`support.categories.${option}`)}
            onPress={() => setCategory(option)}
            testID={`support-category-${option}`}
          />
        ))}
        <Text style={styles.detail} testID="support-selected-category">
          {t(`support.categories.${category}`)}
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('support.subject')}</Text>
        <TextInput
          style={styles.input}
          value={subject}
          onChangeText={setSubject}
          accessibilityLabel={t('support.subject')}
          testID="support-subject"
        />
        <Text style={styles.sectionTitle}>{t('support.body')}</Text>
        <TextInput
          style={[styles.input, styles.multiline]}
          value={body}
          onChangeText={setBody}
          multiline
          accessibilityLabel={t('support.body')}
          testID="support-body"
        />
      </View>

      {receipts.length > 0 ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>{t('support.attach')}</Text>
          {receipts.map(receipt => (
            <SecondaryButton
              key={receipt.order_id}
              label={receipt.reference}
              onPress={() => setOrderId(receipt.order_id)}
              testID={`support-attach-${receipt.order_id}`}
            />
          ))}
          {orderId ? (
            <Text style={styles.detail} testID="support-attached">
              {t('support.attached', {
                summary:
                  receipts.find(receipt => receipt.order_id === orderId)?.reference ??
                  orderId,
              })}
            </Text>
          ) : null}
        </View>
      ) : null}

      <PrimaryButton
        label={t('support.submit')}
        onPress={() => onSubmit({ category, subject, body, orderId })}
        disabled={!canSubmit}
        testID="support-submit"
      />

      {requests.length === 0 ? (
        <Text style={styles.body} testID="support-empty">
          {t('support.empty')}
        </Text>
      ) : null}

      {requests.map(request => (
        <View
          key={request.request_id}
          style={styles.card}
          testID={`support-request-${request.request_id}`}
        >
          <Text style={styles.reference}>{request.reference}</Text>
          <Text style={styles.body}>{request.subject}</Text>
          <Text style={styles.detail}>{t(`support.states.${request.state}`)}</Text>
          {request.subject_summary ? (
            <Text style={styles.detail}>
              {t('support.attached', { summary: request.subject_summary })}
            </Text>
          ) : null}
        </View>
      ))}

      <SecondaryButton label={t('actions.refresh')} onPress={onBack} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: color.gray50 },
  content: { padding: space.space5, gap: space.space4 },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  card: {
    padding: space.space4,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: color.gray200,
    backgroundColor: color.white,
    gap: space.space2,
  },
  sectionTitle: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  reference: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    fontWeight: '600',
    color: color.gray900,
  },
  body: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  detail: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  input: {
    borderWidth: 1,
    borderColor: color.gray300,
    borderRadius: radius.card,
    padding: space.space3,
    fontSize: typography.body.fontSize,
    color: color.gray900,
  },
  multiline: { minHeight: 96, textAlignVertical: 'top' },
  sent: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.success700,
  },
  error: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.error700,
  },
});
