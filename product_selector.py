import sys,argparse,json,re,csv
from pathlib import Path
from collections import namedtuple

fOutputFilename = 'output_filename'
fDuplicatesFilename = 'duplicates_filename'
fAllNamesFilename = 'all_skus_filename'

def readConfig(Args):
    dump=False
    if Args.cfg is not None:
        try:
            with Args.cfg.open() as jsonFile:
                cfg = json.load(jsonFile)
            print('config file loaded succesfully')
            return cfg
        except json.decoder.JSONDecodeError:
            print('config file corrupted, reverting to defaults')
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

def prepareInputs(Args):
    Cfg = readConfig(Args)
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

def loadItems(filename, columns, replacement, include0PricedItems, translateSku, verbose):
    Item = namedtuple('Item', ['filename','sku', 'price','availability','orig_availability','optionalColumns'])
    Items = {}

    priceReplacement = replacement['price'] if 'price' in replacement else {}
    availreplacement = replacement['availability'] if 'availability' in replacement else {}

    if verbose: print('loading file : ',filename)
    firstLine=True
    with open(filename) as csvfile:
        line = csvfile.readline()
        sep=detectSeparator(line)
        if verbose: 
            sepn = {'\t':'tab', ',':'comma'}[sep]
            print( f"file {filename} using { sepn } separator" )
        csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter=sep)
        for row in reader:
            if firstLine:
                skuIdx = getColumnIdx(row,columns['sku'])
                priceIdx = getColumnIdx(row,columns['price'])
                availabilityIdx = getColumnIdx(row,columns['availability'])
                if skuIdx is None or priceIdx is None or availabilityIdx is None:
                    print(f'error loading titles : skuIdx {skuIdx}, priceIdx {priceIdx} availabilityIdx {availabilityIdx}')
                    print(row)
                    return None
                optionalColumns = {k : getColumnIdx(row,v) for k,v in columns.items() if k not in ('sku','price','availability')}
                if verbose: print(f'loading titles : skuIdx {skuIdx}, priceIdx {priceIdx} availabilityIdx {availabilityIdx}')
                if verbose: print(f'loading titles : sku {row[skuIdx]}, price {row[priceIdx]} availability {row[availabilityIdx]}')
                lineNo=2
                firstLine = False
            else:
                try:
                    opt = { k:getAt(row, v) for k,v in optionalColumns.items() }
                    #availability = convertAvailability( row, availabilityIdx, availreplacement )
                    availability = getAt(row, availabilityIdx, availreplacement)
                    avr = availabilityToRange(availability)
                    if avr[1] <=0 : continue
                    sku = getAt(row, skuIdx)
                    try:
                        price = float(getAt(row, priceIdx,priceReplacement))
                        invalidPrice = price==0 and not include0PricedItems
                        if not invalidPrice:
                            skut = translateSku(sku)
                            item = Item(filename.name, sku, price, availability, row[availabilityIdx], opt)
                            Items[skut] = item
                    except ValueError:
                        invalidPrice=True
                    if verbose: print(f'skippint item {sku} with invalid price {row[priceIdx]}')
                except IndexError:
                    pass
                except ValueError:
                    print(f'ValueError at {lineNo} sku {sku} 1st column {row[0]}')
                    print(row)
                    raise
                lineNo+=1
    print( f'Loaded {len(Items)} items from file {filename}')
    return Items

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

def selectItems(Items):
    SelectedItems = {}
    Duplicates = []
    for f,items in Items.items():
        print('adding items from file',f)
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
        print(f'found {dupCnt} duplicates, total selected items {len(SelectedItems)}')
    return SelectedItems, Duplicates

def main(Args):
    Cfg = prepareInputs(Args)
    Files = [x for x in Args.dir.iterdir() if x.is_file() and x.suffix.lower() in ('.csv','.txt')]

    columns = Cfg['columns']
    outputFn = Path(Cfg[fOutputFilename])
    replacement = Cfg['replace']
    duplicatesFn = Cfg[fDuplicatesFilename]
    allnamesFn = Cfg[fAllNamesFilename]
    zpi = Cfg["inlude_0_priced_items"]
    ignoreSkuCase = Cfg["sku_ignore_case"]

    tt = str.maketrans( {c:None for c in Cfg['sku_chars_to_remove']} )
    def translateSku(sku):
        skut = sku.translate(tt)
        if ignoreSkuCase:
            skut = skut.lower()
        return skut
    
    Items = { f:loadItems(f, columns, replacement, zpi, translateSku, Args.verbose) for f in Files }
    SelectedItems,Duplicates = selectItems(Items)
    
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
    parser.add_argument("-cfg",type=Path,help="config file path and name")
    parser.add_argument("-verbose","-v",action='store_true',help="print debug informations")
    Args = parser.parse_args()
    main(Args)
