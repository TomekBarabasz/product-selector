import sys,argparse,json,re,csv
from pathlib import Path
from collections import namedtuple

fOutputFilename = 'output_filename'
fDuplicatesFilename = 'duplicates_filename'
fAllNamesFilename = 'all_skus_filename'

def readConfig(Args, verbose):
    dump=False
    if Args.cfg is not None:
        try:
            with Args.cfg.open() as jsonFile:
                cfg = json.load(jsonFile)
            verbose('config file loaded succesfully')
            return cfg
        except json.decoder.JSONDecodeError:
            verbose('config file corrupted, reverting to defaults')
            dump=True
    
    #default configuration
    cfg = { 'columns' : 
            {
                'sku'   : ('SUPPLIER_PART_NUMBER','MANUFACTURER SKU', 'Vendor Part Number'),
                'price' : ('RESELLER_BUY_EX','DBP','Retail Price'),
                'availability' : ('TOTAL_AVAILABILITY','AT','Available Quantity'),
                "upc"         : ("UPC", "EANUPC Code","STOCK CODE")
            },
            'replace' : { 'availability' : {'B':0, 'CALL':0}},
            'sku_chars_to_remove' : ' -_=/.',
            fOutputFilename : Args.out,
            fDuplicatesFilename : None,
            fAllNamesFilename : None,
            'inlude_0_priced_items' : False
        }
    if dump:
        with open('default_config.json', 'w') as outfile:
            json.dump(cfg, outfile)
    return cfg

def prepareInputs(Args,verbose):
    Cfg = readConfig(Args,verbose)
    if Args.output is not None:
        Cfg[fOutputFilename]=Args.output
    if fOutputFilename not in Cfg or Cfg[fOutputFilename] is None:
        Cfg[fOutputFilename]='results.csv'
    if 'sku_chars_to_remove' not in Cfg or Cfg['sku_chars_to_remove'] is None:
        Cfg['sku_chars_to_remove']={}
    if Args.duplicates is not None:
        Cfg[fDuplicatesFilename] = Args.duplicates 
    if Args.names is not None:
        Cfg[fAllNamesFilename] = Args.names
    if "inlude_0_priced_items" not in Cfg or Cfg["inlude_0_priced_items"] is None:
        Cfg["inlude_0_priced_items"] = False
    if 'replace' not in Cfg or Cfg['replace'] is None:
        Cfg['replace'] = {}
    if "sku_ignore_case" not in Cfg or Cfg["sku_ignore_case"] is None:
        Cfg["sku_ignore_case"] = True
    if 'encodings' not in Cfg or Cfg['encodings'] is None:
        Cfg['encodings'] = (None, "utf-8", "cp1252", "ISO-8859-1")
    return Cfg

def getColumnIdx(sline,Titles):
    for title in Titles:
        try:
            idx = sline.index(title)
            return idx
        except ValueError:
            pass
    return None

def createSplitter(line):
    def splitByTabs(line):
        return line.split('\t')
    def spliltByRegex(line):
        #sline = re.split(r',\s*(?![^()]*\))', line)
        #return re.findall("[^()]*\([^()]*\),?",line)
        sline= re.split(',"|",',line)
        return [e.replace('"','') for e in sline]
    def spliltByComma(line):
        return line.split(',')
    if line.count('\t')>=2:
        print('using tab split')
        return splitByTabs
    elif line.count('"')>=6:
        print('using regex split')
        return spliltByRegex
    else:
        print('using comma split')
        return spliltByComma

def detectSeparator(line,):
    if line.count('\t')>=2:
        return '\t'
    else:
        return ','

def getAt(arr,idx,replacement={}): 
    if idx is not None:
        v = arr[idx]
        v = v.replace('"','')
        v = v.strip()
        if v in replacement:
            v = replacement[v]
        return v
    else:
        return ''

def availabilityToRange(avail):
    try:
        v = int(avail)
        return (v,v)
    except ValueError:
        if avail[0]=='>':
            return (int(avail[1:]), sys.maxsize)
        elif avail[0]=='<':
            return (1,int(avail[1:]))
        raise

def covertToType(string,type):
    try:
        return type(string)
    except ValueError:
        return None

def _loadItems(filename, columns, replacement, include0PricedItems, translateSku, encoding, verbose):
    Item = namedtuple('Item', ['filename','sku', 'price','availability','orig_availability','optionalColumns'])
    Items = {}

    priceReplacement = replacement['price'] if 'price' in replacement else {}
    availreplacement = replacement['availability'] if 'availability' in replacement else {}

    firstLine=True
    with open(filename, encoding=encoding) as csvfile:
        line = csvfile.readline()
        sep=detectSeparator(line)
        invalidLines = 0
        invalidPrices = 0
        csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter=sep)
        for row in reader:
            if firstLine:
                skuIdx = getColumnIdx(row,columns['sku'])
                priceIdx = getColumnIdx(row,columns['price'])
                availabilityIdx = getColumnIdx(row,columns['availability'])
                if skuIdx is None or priceIdx is None or availabilityIdx is None:
                    verbose(f'error loading titles : skuIdx {skuIdx}, priceIdx {priceIdx} availabilityIdx {availabilityIdx}')
                    verbose(row)
                    return None
                optionalColumns = {k : getColumnIdx(row,v) for k,v in columns.items() if k not in ('sku','price','availability')}
                skuTitle = row[skuIdx]
                priceTitle = row[priceIdx]
                availabilityTitle = row[availabilityIdx]
                firstLine = False
            else:
                try:
                    opt = { k:getAt(row, v) for k,v in optionalColumns.items() }
                    availability = getAt(row, availabilityIdx, availreplacement)
                    avr = availabilityToRange(availability)
                    if avr[1] <=0 : continue
                    sku = getAt(row, skuIdx)
                    price = covertToType(getAt(row, priceIdx,priceReplacement), float)
                    if price is None:
                        invalidPrices += 1
                    elif price==0 and not include0PricedItems:
                        invalidPrices += 1
                    else:
                        skut = translateSku(sku)
                        item = Item(filename.name, sku, price, availability, row[availabilityIdx], opt)
                        Items[skut] = item
                except IndexError:
                    invalidLines += 1
    
    sepn = 'comma' if sep==',' else 'tab'
    verbose(f'file {filename} separator "{sepn}" encoding {encoding}')
    verbose(f'\tloaded {len(Items)} items')
    verbose(f'\tskipped {invalidPrices} items without a price')
    verbose(f'\tskipped {invalidLines} invalid lines')
    verbose(f'\ttitle indices: skuIdx "{skuIdx}", priceIdx "{priceIdx}" availabilityIdx "{availabilityIdx}"')
    verbose(f'\ttitle names: sku "{skuTitle}", price "{priceTitle}" availability "{availabilityTitle}"')
    return Items

def loadItems(filename, columns, replacement, include0PricedItems, translateSku, encodings, verbose):
    for enc in encodings:
        try:
            itms = _loadItems(filename, columns, replacement, include0PricedItems, translateSku, enc, verbose)
            if itms is not None:
                return itms
        except:
            pass
    verbose(f'DecodeError when reading file {filename} - skipping')
    return None

def printItems(Items):
    for filename,items in Items.items():
        cnt=5
        print('items in ',filename)
        for i in items:
            print(i)
            cnt-=1
            if cnt <=0: break

def findMatching(Items, name):
    for iname,item in Items.items():
        if iname==name:
            return iname,item
    return None,None

# note return -1 if a < b
# 0 if a==0
# 1 if a>b
def compareAvailability(a, b):
    ra = availabilityToRange(a)
    rb = availabilityToRange(b)
    # a----a b------b
    if ra[1] < rb[0]: return -1
    #b----b a-----a
    elif rb[1] < ra[0]: return 1
    # a----a
    #    b--------b
    elif ra[1] < rb[1]: return -1
    # b----b
    #    a--------a
    elif rb[1] < ra[1]: return 1
    else: return 0

def selectItems(Items, verbose):
    SelectedItems = {}
    Duplicates = []
    verbose('adding items')
    itemsCnt = 0
    for f,items in Items.items():
        dupCnt=0
        for name,item in items.items():
            selName,selItem = findMatching(SelectedItems, name)
            if selName is not None:
                Duplicates.append( (item,selItem) )
                dupCnt += 1
                if item.price < selItem.price and availabilityToRange(item.availability)[0]>0:# compareAvailability(item.availability, selItem.availability)>=0:
                    SelectedItems[name] = item   
            else:
                SelectedItems[name]=item
        totItems = len(SelectedItems)
        verbose(f'\tfile {f } : {dupCnt} duplicates, added {totItems-itemsCnt} items, total items {totItems}')
        itemsCnt = totItems
    return SelectedItems, Duplicates

def makeVerbose(Args):
    def dummy(txt):pass
    def toConsole(txt):
        print(txt)
    def toFile(txt):
        summaryFile.write(txt+'\n')
    if Args.verbose:
        return toConsole
    elif Args.summary:
        summaryFile = open(Args.summary,'w')
        return toFile
    else:
        return dummy

def main(Args):
    verbose = makeVerbose(Args)
    Cfg = prepareInputs(Args,verbose)
    Files = [x for x in Args.dir.iterdir() if x.is_file() and x.suffix.lower() in ('.csv','.txt')]

    columns = Cfg['columns']
    outputFn = Path(Cfg[fOutputFilename])
    replacement = Cfg['replace']
    duplicatesFn = Cfg[fDuplicatesFilename]
    allnamesFn = Cfg[fAllNamesFilename]
    zpi = Cfg["inlude_0_priced_items"]
    ignoreSkuCase = Cfg["sku_ignore_case"]
    encodings = Cfg['encodings']

    tt = str.maketrans( {c:None for c in Cfg['sku_chars_to_remove']} )
    def translateSku(sku):
        skut = sku.translate(tt)
        if ignoreSkuCase:
            skut = skut.lower()
        return skut
    
    Items = {}
    for f in Files:
        itms = loadItems(f, columns, replacement, zpi, translateSku, encodings, verbose)
        if itms is not None:
            Items[f]=itms
    
    SelectedItems,Duplicates = selectItems(Items, verbose)
    
    with open(outputFn,'w') as outf:
        row = 'sku,filename,price,availability'
        for i in SelectedItems.values():
            for n in i.optionalColumns.keys():
                row += ','+n
            break
        outf.write(row+'\n')
        for item in SelectedItems.values():
            row = f'"{item.sku}",{item.filename},{item.price}, {item.orig_availability}'
            for v in item.optionalColumns.values():
                row += ',' + v
            outf.write( row + '\n')
    
    if duplicatesFn is not None:
        with open(duplicatesFn,'w') as outf:
            outf.write('sku 1,filename 1,sku 2,filename 2,price 1,price 2,availability 1,availability 2\n')
            for i1,i2 in Duplicates:
                outf.write( f'"{i1.sku}",{i1.filename},"{i2.sku}",{i2.filename},{i1.price},{i2.price},{i1.orig_availability},{i2.orig_availability}\n' )
    
    if allnamesFn is not None:
        with open(allnamesFn,'w') as outf:
            outf.write('sku,filename\n')
            for itms in Items.values():
                for i in itms.values():
                    outf.write(f'"{i.sku}",{i.filename}\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("dir",type=Path,help="directory containing input (datafeed) files")
    parser.add_argument("-output","-o", type=Path,help="output file path and name")
    parser.add_argument("-duplicates","-d",type=Path,help="duplicates file path and name")
    parser.add_argument("-names","-n",type=Path,help="all names file path and name")
    parser.add_argument("-summary","-s",type=Path,help="summary file path and name")
    parser.add_argument("-cfg",type=Path,help="config file path and name")
    parser.add_argument("-verbose","-v",action='store_true',help="print debug informations")
    Args = parser.parse_args()
    main(Args)
