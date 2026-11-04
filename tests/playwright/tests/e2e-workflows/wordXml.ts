/**
 * Reads `word/document.xml` out of a Word (.docx) file's bytes with Node's own zlib, so the specs that check a printed
 * report need no `unzip` binary (the Playwright image does not ship one).
 */
import zlib from "node:zlib";

const END_OF_CENTRAL_DIRECTORY = 0x06054b50;
const CENTRAL_DIRECTORY_ENTRY = 0x02014b50;
const LOCAL_FILE_HEADER = 0x04034b50;

/**
 * The text of one entry of a zip file.
 *
 * @param zip The whole file.
 * @param entry The entry's path inside the zip, such as `word/document.xml`.
 * @returns The entry decoded as UTF-8.
 * @throws If the bytes are not a zip, or have no such entry, or the entry uses a method other than stored or deflate.
 */
export function zipEntryText(zip: Buffer, entry: string): string {
  let end = zip.length - 22;
  while (end >= 0 && zip.readUInt32LE(end) !== END_OF_CENTRAL_DIRECTORY) end -= 1;
  if (end < 0) throw new Error("Not a zip file");
  const count = zip.readUInt16LE(end + 10);
  let at = zip.readUInt32LE(end + 16);
  for (let i = 0; i < count; i += 1) {
    if (zip.readUInt32LE(at) !== CENTRAL_DIRECTORY_ENTRY) throw new Error("Damaged zip directory");
    const method = zip.readUInt16LE(at + 10);
    const size = zip.readUInt32LE(at + 20);
    const nameLength = zip.readUInt16LE(at + 28);
    const extraLength = zip.readUInt16LE(at + 30);
    const commentLength = zip.readUInt16LE(at + 32);
    const local = zip.readUInt32LE(at + 42);
    const name = zip.toString("utf8", at + 46, at + 46 + nameLength);
    at += 46 + nameLength + extraLength + commentLength;
    if (name !== entry) continue;
    if (zip.readUInt32LE(local) !== LOCAL_FILE_HEADER) throw new Error("Damaged zip entry");
    const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
    const data = zip.subarray(start, start + size);
    if (method === 0) return data.toString("utf8");
    if (method === 8) return zlib.inflateRawSync(data).toString("utf8");
    throw new Error(`Unsupported zip method ${method}`);
  }
  throw new Error(`No ${entry} in the zip`);
}

/**
 * The text of `word/document.xml` inside a Word file.
 *
 * @param bytes The .docx file's bytes.
 * @returns The document's XML.
 */
export function wordXml(bytes: Buffer): string {
  return zipEntryText(bytes, "word/document.xml");
}
