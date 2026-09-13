import React, { useMemo } from 'react';
import Svg, { Path, Rect } from 'react-native-svg';
import qrcode from 'qrcode-generator';

/** Encode locally in memory. No URL, image file, analytics or clipboard copy. */
export function InstallationQr({ lpa }: { lpa: string }): React.JSX.Element | null {
  const matrix = useMemo(() => {
    try {
      const qr = qrcode(0, 'M');
      qr.addData(lpa, 'Byte');
      qr.make();
      const size = qr.getModuleCount();
      const cells: string[] = [];
      for (let row = 0; row < size; row += 1) {
        for (let column = 0; column < size; column += 1) {
          if (qr.isDark(row, column)) {
            cells.push(`M${column + 4},${row + 4}h1v1h-1z`);
          }
        }
      }
      return { size: size + 8, path: cells.join('') };
    } catch {
      return null; // Manual fields remain available if the value cannot encode.
    }
  }, [lpa]);
  if (!matrix) { return null; }
  return (
    <Svg width="100%" height={240} viewBox={`0 0 ${matrix.size} ${matrix.size}`}
      testID="install-qr" accessible={false}>
      <Rect width={matrix.size} height={matrix.size} fill="white" />
      <Path d={matrix.path} fill="black" />
    </Svg>
  );
}
