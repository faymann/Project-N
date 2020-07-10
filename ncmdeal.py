import binascii, struct
import base64, json, os, sys

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from Crypto.Util.strxor import strxor
from mutagen import mp3, flac, id3

def dump(input_path):

    f = open(input_path, 'rb')
    # 开头都一样，不一样解不了密
    header = f.read(8)
    assert binascii.b2a_hex(header) == b'4354454e4644414d'

    f.seek(2, 1)

    # key data， 要翻译成小端的unsigned int
    key_length = f.read(4)
    key_length = struct.unpack('<I', bytes(key_length))[0]

    # AES-ECB 密文
    key_data = bytearray(f.read(key_length))
    key_data = bytes(bytearray([byte ^ 0x64 for byte in key_data]))

    # AES-ECB 解密
    core_key = binascii.a2b_hex('687A4852416D736F356B496E62617857') # 神奇的key，hashcat还是有内鬼？
    cryptor = AES.new(core_key, AES.MODE_ECB)
    # decrypt 前17位是 neteasecloudmusic，采用pkcs7 padding方式
    key_data = unpad(cryptor.decrypt(key_data), 16)[17:] 
    key_length = len(key_data)

    # S-box (标准 RC4 KSA)
    key = bytearray(key_data)
    S = bytearray(range(256))
    j = 0

    for i in range(256):
        j = (j + S[i] + key[i % key_length]) & 0xFF
        S[i], S[j] = S[j], S[i]

    # meta data，要翻译成小端的unsigned int
    meta_length = f.read(4)
    meta_length = struct.unpack('<I', bytes(meta_length))[0]

    if meta_length:
        meta_data = bytearray(f.read(meta_length))
        meta_data = bytes(bytearray([byte ^ 0x63 for byte in meta_data]))
        identifier = meta_data.decode('utf-8') # 惊现 '163 key(Don't modify):' 内鬼？
        # base64 解码
        meta_data = base64.b64decode(meta_data[22:])
        # 第二次 AES-ECB 解密
        meta_key = binascii.a2b_hex('2331346C6A6B5F215C5D2630553C2728')
        cryptor = AES.new(meta_key, AES.MODE_ECB)
        meta_data = unpad(cryptor.decrypt(meta_data), 16).decode('utf-8')
        # 解密出来一个 json 格式文件
        meta_data = json.loads(meta_data[6:])
    else:
        # 没有 json 文件确定格式的话，就用文件大小区分(>16m)
        meta_data = {'format': 'flac' if os.fstat(f.fileno()).st_size > 16777216 else 'mp3'}

    f.seek(5, 1)

    # 专辑封面图片
    image_space = f.read(4)
    image_space = struct.unpack('<I', bytes(image_space))[0]
    image_size = f.read(4)
    image_size = struct.unpack('<I', bytes(image_size))[0]
    image_data = f.read(image_size) if image_size else None

    f.seek(image_space - image_size, 1)

    # 音乐输出地址
    output_path = os.path.splitext(input_path)[0] + '.' + meta_data['format']
    # 已转换过的不做无用功
    if os.path.exists(output_path): return
    # 剩下全是音乐文件
    data = f.read()
    f.close()

    # 音乐文件主体部分 (修改的RC4-PRGA，没有用 j 加和随机化)
    # 直接循环的话会丢失最后几秒
    stream = [S[(S[i] + S[(i + S[i]) & 0xFF]) & 0xFF] for i in range(256)]
    stream = bytes(bytearray(stream * (len(data) // 256 + 1))[1:1 + len(data)])
    data = strxor(data, stream)

    m = open(output_path, 'wb')
    m.write(data)
    m.close()

    # 处理专辑封面
    if image_data:
        if meta_data['format'] == 'flac':
            audio = flac.FLAC(output_path)
            image = flac.Picture()
            image.encoding = 0
            image.type = 3
            image.mime = 'image/png' if image_data[0:4] == binascii.a2b_hex('89504E47') else 'image/jpeg' # png开头是\x89 P N G
            image.data = image_data
            audio.clear_pictures()
            audio.add_picture(image)
            audio.save()
        elif meta_data['format'] == 'mp3':
            audio = mp3.MP3(output_path)
            image = id3.APIC()
            image.encoding = 0
            image.type = 6
            image.mime = 'image/png' if image_data[0:4] == binascii.a2b_hex('89504E47') else 'image/jpeg' # png开头是\x89 P N G
            image.data = image_data
            audio.tags.add(image)
            audio.save()
    
    # 添加音乐相关信息
    if meta_length:
        if meta_data['format'] == 'flac':
            audio = flac.FLAC(output_path)
            audio['description'] = identifier
        else:
            audio = mp3.EasyMP3(output_path)
            audio['title'] = 'placeholder'
            audio.tags.RegisterTextKey('comment', 'COMM')
            audio['comment'] = identifier
        audio['title'] = meta_data['musicName']
        audio['album'] = meta_data['album']
        audio['artist'] = '/'.join([artist[0] for artist in meta_data['artist']])
        audio.save()

    return output_path

def main(argv):
    for path in argv[1:]:
        dump(path)

if __name__ == '__main__':
    main(sys.argv)
