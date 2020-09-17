import sys,argparse,json,re,csv,unittest
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
            fOutputFilename : Args.output,
            fDuplicatesFilename : None,
            fAllNamesFilename : None,
            'inlude_0_priced_items' : False
        }
    if dump:
        with open('default_config.json', 'w') as outfile:
            json.dump(cfg, outfile)
    return cfg

def makeShippingCostRule(Rules,parseRange):
    def calcShippingCost(price,weight):
        if free_above_price is not None and price > free_above_price:
            return 0
        if na_price is not None and weight is None:
            return na_price
        for r in Ranges:
            if weight >= r[0] and weight <=r[1]: return r[2] + per_product_price
        if per_product_price is None:
            print('invalid shippng cost rules',price, weight)
        return per_product_price
    Ranges = []
    free_above_price = None
    per_product_price = 0
    na_price = None
    for k,v in Rules.items():
        rg,units = parseRange(k)
        if rg is not None and units=='kg':
            Ranges.append( (rg[0],rg[1],float(v)) ) #[ rg ] = float(v)
            continue
        if k=='free':
            rg,units = parseRange(v)
            if rg is not None and units=='$':
                free_above_price = rg[0]
            continue
        if k=='NA':
            na_price = float(v)
            continue
        if k=='per_product':
            per_product_price = float(v)
    Ranges = sorted(Ranges)
    return calcShippingCost

def loadShippingCostRules(ShippingRules):
    def parseRange(string):
        m = x1.match(string)
        if m is not None:
            g = m.groups()
            return (float(g[0]),float(g[1])), 'kg'
        m = x2.match(string)
        if m is not None:
            g = m.groups()
            return (float(g[0]),sys.maxsize), g[1]
        return None,None
    x1 = re.compile('(\d+.*\d*)-(\d+.*\d*)kg')
    x2 = re.compile('>(\d+.*\d*)(kg|\$)')
    Rules = {supplier : makeShippingCostRule(rules,parseRange) for supplier,rules in ShippingRules.items()}
    return Rules

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
    Cfg['shipping'] = loadShippingCostRules(Cfg['shipping_rules']) if 'shipping_rules' in Cfg else {}
    return Cfg

def getColumnIdx(sline,Titles):
    for title in Titles:
        title = title.lower()
        for i in range(len(sline)):
            if sline[i].lower() == title:
                return i
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

def _loadItems(filename, supplier, columns, replacement, include0PricedItems, translateSku, encoding, shippingCostFcn, verbose):
    Item = namedtuple('Item', ['supplier','sku', 'price','tot_cost','availability','orig_availability','optionalColumns'])
    Items = {}
    priceReplacement = replacement['price'] if 'price' in replacement else {}
    availreplacement = replacement['availability'] if 'availability' in replacement else {}
    weightReplacement = replacement['weight'] if 'weight' in replacement else {}
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
                weightIdx = getColumnIdx(row,columns['weight'])
                if skuIdx is None or priceIdx is None or availabilityIdx is None:
                    verbose(f'error loading titles : skuIdx {skuIdx}, priceIdx {priceIdx} availabilityIdx {availabilityIdx} weightIdx {weightIdx}')
                    verbose(row)
                    return None
                optionalColumns = {k : getColumnIdx(row,v) for k,v in columns.items() if k not in ('sku','price','availability','weight')}
                skuTitle = row[skuIdx]
                priceTitle = row[priceIdx]
                availabilityTitle = row[availabilityIdx]
                weightTitle = row[weightIdx] if weightIdx is not None else ''
                firstLine = False
            else:
                try:
                    opt = { k:getAt(row, v) for k,v in optionalColumns.items() }
                    availability = getAt(row, availabilityIdx, availreplacement)
                    avr = availabilityToRange(availability)
                    if avr[1] <=0 : continue
                    sku = getAt(row, skuIdx)
                    price = covertToType(getAt(row, priceIdx, priceReplacement), float)

                    weight = covertToType(getAt(row, weightIdx, weightReplacement), float) if weightIdx is not None else 0
                    if price is None:
                        invalidPrices += 1
                    elif price==0 and not include0PricedItems:
                        invalidPrices += 1
                    else:
                        skut = translateSku(sku)
                        shc = shippingCostFcn(price,weight) if shippingCostFcn is not None else 0
                        item = Item(supplier, sku, price, price+shc, availability, row[availabilityIdx], opt)
                        Items[skut] = item
                except IndexError:
                    invalidLines += 1
                except ValueError:
                    print('ValueError ', row)
    
    sepn = 'comma' if sep==',' else 'tab'
    verbose(f'file {filename} separator "{sepn}" encoding {encoding}')
    verbose(f'\tloaded {len(Items)} items')
    verbose(f'\tskipped {invalidPrices} items without a price')
    verbose(f'\tskipped {invalidLines} invalid lines')
    verbose(f'\ttitle indices: skuIdx "{skuIdx}", priceIdx "{priceIdx}" availabilityIdx "{availabilityIdx}" weightIdx "{weightIdx}"')
    verbose(f'\ttitle names: sku "{skuTitle}", price "{priceTitle}" availability "{availabilityTitle}" weight "{weightTitle}"')
    return Items

def loadItems(filename, supplier, columns, replacement, include0PricedItems, translateSku, encodings, shippingCostFcn, verbose):
    for enc in encodings:
        try:
            itms = _loadItems(filename, supplier, columns, replacement, include0PricedItems, translateSku, enc, shippingCostFcn, verbose)
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
                if item.tot_cost < selItem.tot_cost and availabilityToRange(item.availability)[0]>0:# compareAvailability(item.availability, selItem.availability)>=0:
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

def readDataFiles(dir,Cfg):
    FnToSupplier = {v.lower():k for k,v in Cfg['suppliers'].items()} if 'suppliers' in Cfg else {}
    Files = {}
    for fn in dir.iterdir():
        if fn.is_file() and fn.suffix.lower() in ('.csv','.txt'):
            name = fn.name.lower()
            name = FnToSupplier[name] if name in FnToSupplier else fn.name
            Files[name]=fn
    return Files

def writeResult(SelectedItems,outputFn):
    with open(outputFn,'w') as outf:
        row = 'sku,supplier,price,price+shipping,availability'
        for i in SelectedItems.values():
            for n in i.optionalColumns.keys():
                row += ','+n
            break
        outf.write(row+'\n')
        for item in SelectedItems.values():
            row = f'"{item.sku}",{item.supplier},{item.price},{item.tot_cost},{item.orig_availability}'
            for v in item.optionalColumns.values():
                row += ',' + v
            outf.write( row + '\n')

def writeDuplicates(Duplicates, duplicatesFn):
    if duplicatesFn is not None:
        with open(duplicatesFn,'w') as outf:
            outf.write('sku 1,supplier 1,sku 2,supplier 2,price 1,total cost 1,price 2,total cost 2,availability 1,availability 2\n')
            for i1,i2 in Duplicates:
                outf.write( f'"{i1.sku}",{i1.supplier},"{i2.sku}",{i2.supplier},{i1.price},{i1.tot_cost},{i2.price},{i2.tot_cost},{i1.orig_availability},{i2.orig_availability}\n' )

def writeNames(Items, allnamesFn):   
    if allnamesFn is not None:
        with open(allnamesFn,'w') as outf:
            outf.write('sku,supplier\n')
            for itms in Items.values():
                for i in itms.values():
                    outf.write(f'"{i.sku}",{i.supplier}\n')

def main(Args):
    verbose = makeVerbose(Args)
    Cfg = prepareInputs(Args,verbose)
    Files = readDataFiles(Args.dir, Cfg)

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
    for supplier,file_ in Files.items():
        shippingCostFcn = Cfg['shipping'][supplier] if supplier in Cfg['shipping'] else None
        itms = loadItems(file_, supplier, columns, replacement, zpi, translateSku, encodings, shippingCostFcn, verbose)
        if itms is not None:
            Items[supplier]=itms
    
    SelectedItems,Duplicates = selectItems(Items, verbose)
    
    writeResult(SelectedItems,outputFn)
    writeDuplicates(Duplicates, duplicatesFn)
    writeNames(Items, allnamesFn)

class TestShippingRules(unittest.TestCase):
    def test_1(self):
        calc_shc = loadShippingCostRules({'dummy':{
                                        ">5kg"  : 25,
                                        "3-5kg" : 17.5,
                                        "0-3kg" : 12,
                                        "NA"    : 15,
                                        "free"  : ">1000$" }})['dummy']
        self.assertEqual(calc_shc(1,    None),  15) #NA weight
        self.assertEqual(calc_shc(1,    0),     12)
        self.assertEqual(calc_shc(1,    3),     12)
        self.assertEqual(calc_shc(1,    3.01),  17.5)
        self.assertEqual(calc_shc(1,    5),     17.5)
        self.assertEqual(calc_shc(1,    5.01),  25)
        self.assertEqual(calc_shc(1,    15),    25)

        self.assertEqual(calc_shc(999,    0),   12)
        self.assertEqual(calc_shc(1000,   15),  25)

        self.assertEqual(calc_shc(1000.1, 0),   0)
        self.assertEqual(calc_shc(1000.1, 5),   0)
        self.assertEqual(calc_shc(1000.1, 15),  0)

    def test_2(self):
        calc_shc = loadShippingCostRules({'dummy':{
                                        "per_product" : 15,
                                        "free" : ">300$",
                                        "NA" : 10 }})['dummy']
        self.assertEqual(calc_shc(1,    None),  10) #NA weight
        self.assertEqual(calc_shc(1,    1),     15)
        self.assertEqual(calc_shc(1,    5),     15)
        self.assertEqual(calc_shc(1,    10),    15)
        self.assertEqual(calc_shc(1,    15),    15)
        self.assertEqual(calc_shc(299,  15),    15)
        self.assertEqual(calc_shc(300,  15),    15)
        self.assertEqual(calc_shc(300.1,15),    0)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("dir",type=Path,help="directory containing input (datafeed) files")
    parser.add_argument("-output","-o", type=Path,help="output file path and name")
    parser.add_argument("-duplicates","-d",type=Path,help="duplicates file path and name")
    parser.add_argument("-names","-n",type=Path,help="all names file path and name")
    parser.add_argument("-summary","-s",type=Path,help="summary file path and name")
    parser.add_argument("-cfg",type=Path,help="config file path and name")
    parser.add_argument("-verbose","-v",action='store_true',help="print debug informations")
    parser.add_argument("-test","-t",action='store_true',help="run unit testing")
    Args = parser.parse_args()

    if Args.test:
        unittest.main(argv=['program_selectory.py'])
    else:
        main(Args)
