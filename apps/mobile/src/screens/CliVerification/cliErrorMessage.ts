import { CliApiError } from '../../api/cliClient';
import { i18n } from '../../i18n';

export function cliErrorMessage(error: unknown): string {
  const code = error instanceof CliApiError ? error.code : 'network_error';
  return i18n.t(`home:callerId.errors.${code}`);
}
