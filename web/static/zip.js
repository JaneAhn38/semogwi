// PNG 여러 장을 ZIP 하나로 묶습니다. PNG는 이미 압축되어 있으므로 압축 없이(store) 저장합니다.
"use strict";

const SemogwiZip = (() => {
  const CRC_TABLE = new Uint32Array(256).map((_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  }

  function header(size, write) {
    const bytes = new Uint8Array(size);
    write(new DataView(bytes.buffer));
    return bytes;
  }

  // files: [{ name, bytes: Uint8Array }]. 이름은 영문·숫자만 씁니다.
  function create(files) {
    const now = new Date();
    const time = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
    const date = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    const encoder = new TextEncoder();
    const parts = [];
    const central = [];
    let offset = 0;

    for (const file of files) {
      const name = encoder.encode(file.name);
      const crc = crc32(file.bytes);
      const size = file.bytes.length;
      const local = header(30, (v) => {
        v.setUint32(0, 0x04034b50, true);
        v.setUint16(4, 20, true);
        v.setUint16(10, time, true);
        v.setUint16(12, date, true);
        v.setUint32(14, crc, true);
        v.setUint32(18, size, true);
        v.setUint32(22, size, true);
        v.setUint16(26, name.length, true);
      });
      parts.push(local, name, file.bytes);
      central.push(
        header(46, (v) => {
          v.setUint32(0, 0x02014b50, true);
          v.setUint16(4, 20, true);
          v.setUint16(6, 20, true);
          v.setUint16(12, time, true);
          v.setUint16(14, date, true);
          v.setUint32(16, crc, true);
          v.setUint32(20, size, true);
          v.setUint32(24, size, true);
          v.setUint16(28, name.length, true);
          v.setUint32(42, offset, true);
        }),
        name,
      );
      offset += local.length + name.length + size;
    }

    const centralSize = central.reduce((sum, part) => sum + part.length, 0);
    const end = header(22, (v) => {
      v.setUint32(0, 0x06054b50, true);
      v.setUint16(8, files.length, true);
      v.setUint16(10, files.length, true);
      v.setUint32(12, centralSize, true);
      v.setUint32(16, offset, true);
    });
    return new Blob([...parts, ...central, end], { type: "application/zip" });
  }

  return { create };
})();
