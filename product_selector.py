import sys,argparse,json,re,csv,unittest,operator
from pathlib import Path
from collections import namedtuple
from datetime import datetime

fOutputFilename = 'output_filename'
fDuplicatesFilename = 'duplicates_filename'
fAllNamesFilename = 'all_skus_filename'

class Supplier:
    pass

def readConfig(Args, verbose):
    if Args.cfg is not None:
        try:
            with Args.cfg.open() as jsonFile:
                cfg = json.load(jsonFile)
            verbose('config file loaded succesfully')
            return cfg
        except json.decoder.JSONDecodeError:
            verbose('config file corrupted, reverting to defaults')
    return None

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
    if ShippingRules is None:   return lambda x: 0
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
    return makeShippingCostRule(ShippingRules, parseRange)

def makeTranslateSku(charsToRemove,ignoreCase):
    tt = str.maketrans( {c:None for c in charsToRemove} )
    def translateSku(sku):
        skut = sku.translate(tt)
        if ignoreCase:
            skut = skut.lower()
        return skut
    return translateSku

def prepareInputs(Args,verbose):
    Cfg = readConfig(Args,verbose)
    if Args.output is not None:
        Cfg[fOutputFilename]=Args.output
    if fOutputFilename not in Cfg or Cfg[fOutputFilename] is None:
        Cfg[fOutputFilename]='results.csv'
    if 'sku_chars_to_remove' not in Cfg or Cfg['sku_chars_to_remove'] is None:
        Cfg['sku_chars_to_remove']=""
    if Args.duplicates is not None:
        Cfg[fDuplicatesFilename] = Args.duplicates 
    if Args.names is not None:
        Cfg[fAllNamesFilename] = Args.names
    if "include_0_priced_items" not in Cfg or Cfg["include_0_priced_items"] is None:
        Cfg["include_0_priced_items"] = False
    if 'replace' not in Cfg or Cfg['replace'] is None:
        Cfg['replace'] = {}
    if "sku_ignore_case" not in Cfg or Cfg["sku_ignore_case"] is None:
        Cfg["sku_ignore_case"] = True
    if 'encodings' not in Cfg or Cfg['encodings'] is None:
        Cfg['encodings'] = (None, "utf-8", "cp1252", "ISO-8859-1")
    if 'include_out_of_stock_items' not in Cfg or Cfg['include_out_of_stock_items'] is None:
        Cfg['include_out_of_stock_items'] = False

    global_settings = ['include_0_priced_items', 'replace', 'sku_chars_to_remove','sku_ignore_case', 'include_out_of_stock_items']
    Suppliers = {}
    for name,supp_def in Cfg['suppliers'].items():
        supp = Supplier()
        for gsn in global_settings:
            val = Cfg[gsn] if gsn not in supp_def else supp_def[gsn]
            setattr(supp,gsn,val)
        supp.name = name
        supp.shipping = loadShippingCostRules(supp_def['shipping_rules'] if 'shipping_rules' in supp_def else None)
        supp.translateSku = makeTranslateSku(supp.sku_chars_to_remove, supp.sku_ignore_case)
        filename = supp_def['data']
        if '*' in filename:
            names = list(Args.dir.glob(filename))
            if len(names)==0:
                verbose( f'filename {filename} not found')
                continue
            supp.data = names[0]
            verbose(f'wildcard in {filename} resolved to {supp.data}')
        else:
            supp.data = Args.dir / filename
        supp.columns = supp_def['columns']
        Suppliers[name]=supp
    
    return Cfg,Suppliers

def getColumnIdx(sline,title):
    try:
        title = title.lower()
        sline = [s.lower() for s in sline]
        return sline.index(title)
    except ValueError:
        return None

def getColumnIndices(sline,title):
    return [ sline.index(c) for c in title.split('+') ]

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
        return (0,0)

def covertToType(string,type):
    try:
        return type(string)
    except ValueError:
        return None

def combineRange(availability_range,r):
    a0 = availability_range[0]
    a1 = availability_range[1]
    if r[0] != 0:
        a0 = min(availability_range[0], r[0])
    a1 = min( sys.maxsize, availability_range[1] + r[1])
    return (a0,a1)

def readAvailability(row, availabilityIdx, availreplacement):
    availability_str = ""
    availability_value=0
    availability_range = (0,0)
    is_value_ok = True
    for i in availabilityIdx:
        a = getAt(row, i, availreplacement)
        r = availabilityToRange(a)
        availability_range = combineRange(availability_range,r)
        if availability_str:
            availability_str += "+"
        availability_str += a
        try:
            availability_value += int(a)
        except ValueError:
            is_value_ok = False
            pass
    return availability_value if is_value_ok else availability_str ,availability_range

def _loadItems(supplier_def, encoding, verbose):
    Item = namedtuple('Item', ['supplier','sku', 'price','tot_cost','availability','orig_availability','optionalColumns'])

    shippingCostFcn = supplier_def.shipping
    replacement = supplier_def.replace
    priceReplacement = replacement['price'] if 'price' in replacement else {}
    availreplacement = replacement['availability'] if 'availability' in replacement else {}
    weightReplacement = replacement['weight'] if 'weight' in replacement else {}
    columns = supplier_def.columns
    firstLine=True
    Items = {}
    t0 = datetime.utcnow()

    with open(supplier_def.data, encoding=encoding) as csvfile:
        line = csvfile.readline()
        sep=detectSeparator(line)
        invalidLines = 0
        invalidPrices = 0
        invalidSku = 0
        outOfStockItems = 0
        csvfile.seek(0)
        reader = csv.reader(csvfile, delimiter=sep)
        for row in reader:
            if firstLine:
                skuIdx = getColumnIdx(row,columns['sku'])
                if skuIdx is None:    
                    cn = columns['sku']
                    verbose(f'error loading sku title {cn}')
                priceIdx = getColumnIdx(row,columns['price'])
                if priceIdx is None:  verbose('error loading price title')
                availabilityIdx = getColumnIndices(row,columns['availability'])
                if availabilityIdx is None: verbose('error loading availability title')
                weightIdx = getColumnIdx(row,columns['weight'])
                if weightIdx is None: verbose('error loading weight title')
                if skuIdx is None or priceIdx is None or availabilityIdx is None or weightIdx is None:
                    verbose(','.join(row))
                    return None
                optionalColumns = {k : getColumnIdx(row,v) for k,v in columns.items() if k not in ('sku','price','availability','weight')}
                firstLine = False
            else:
                try:
                    opt = { k:getAt(row, v) for k,v in optionalColumns.items() }
                    availability,avr = readAvailability(row, availabilityIdx, availreplacement)
                    if avr[1] <=0 and not supplier_def.include_out_of_stock_items: 
                        outOfStockItems += 1
                        continue
                    sku = getAt(row, skuIdx)
                    if not sku:
                        invalidSku += 1
                        continue
                    price = covertToType(getAt(row, priceIdx, priceReplacement), float)

                    weight = covertToType(getAt(row, weightIdx, weightReplacement), float) if weightIdx is not None else 0
                    if price is None:
                        invalidPrices += 1
                    elif price==0 and not supplier_def.include_0_priced_items:
                        invalidPrices += 1
                    else:
                        skut = supplier_def.translateSku(sku)
                        shc = shippingCostFcn(price,weight) if shippingCostFcn is not None else 0
                        item = Item(supplier_def.name, sku, price, price+shc, avr, availability, opt)
                        Items[skut] = item
                except IndexError:
                    invalidLines += 1
                except ValueError:
                    print('ValueError ', row)
    
    sepn = 'comma' if sep==',' else 'tab'
    verbose(f'file {supplier_def.data} separator "{sepn}" encoding {encoding}')
    verbose(f'\tloaded {len(Items)} items time {datetime.utcnow()-t0}')
    verbose(f'\tskipped {invalidPrices} items without a price')
    verbose(f'\tskipped {invalidSku} items with empty sku')
    verbose(f'\tskipped {outOfStockItems} out of stock items')
    verbose(f'\tskipped {invalidLines} invalid lines')
    verbose(f'\ttitle indices: skuIdx "{skuIdx}", priceIdx "{priceIdx}" availabilityIdx "{availabilityIdx}" weightIdx "{weightIdx}"')
    return Items

def loadItems(supplier_def, encodings, verbose):
    if not supplier_def.data.exists():
        verbose( f'filename {supplier_def.data} not found')
        return None,None
    for encoding in encodings:
        try:
            itms = _loadItems(supplier_def, encoding, verbose)
            if itms is not None:
                return itms,encoding
        except UnicodeDecodeError:
            pass
        except Exception as e:     # most generic exception you can catch
            verbose( f'Exception when loading {supplier_def.data} : {e}' )
            pass
    verbose(f'Error reading file {supplier_def.data} - skipping')
    return None,None

def printItems(Items):
    for filename,items in Items.items():
        cnt=5
        print('items in ',filename)
        for i in items:
            print(i)
            cnt-=1
            if cnt <=0: break

def findMatching(Items, name):
    try:
        return name, Items[name]
    except KeyError:
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
        t0 = datetime.utcnow()
        for name,item in items.items():
            selName,selItem = findMatching(SelectedItems, name)
            if selName is not None:
                Duplicates.append( (item,selItem) )
                dupCnt += 1
                if item.tot_cost < selItem.tot_cost and item.availability[1]>0:# compareAvailability(item.availability, selItem.availability)>=0:
                    SelectedItems[name] = item   
            else:
                SelectedItems[name]=item
        dt = datetime.utcnow() - t0
        totItems = len(SelectedItems)
        verbose(f'\tfile {f } : {dupCnt} duplicates, added {totItems-itemsCnt} items, total items {totItems} time {dt}')
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

def writeResult(SelectedItems,outputFn, encoding=None):
    with open(outputFn,'w',encoding=encoding) as outf:
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
            outf.write(row + '\n')

def writeDuplicates(Duplicates, duplicatesFn, encoding=None):
    if duplicatesFn is not None:
        with open(duplicatesFn,'w',encoding=encoding) as outf:
            outf.write('sku 1,supplier 1,sku 2,supplier 2,price 1,total cost 1,price 2,total cost 2,availability 1,availability 2\n')
            for i1,i2 in Duplicates:
                outf.write( f'"{i1.sku}",{i1.supplier},"{i2.sku}",{i2.supplier},{i1.price},{i1.tot_cost},{i2.price},{i2.tot_cost},{i1.orig_availability},{i2.orig_availability}\n' )

def writeNames(Items, allnamesFn,encoding=None):   
    if allnamesFn is not None:
        with open(allnamesFn,'w',encoding=encoding) as outf:
            outf.write('sku,supplier\n')
            for itms in Items.values():
                for i in itms.values():
                    outf.write(f'"{i.sku}",{i.supplier}\n')

def main(Args):
    verbose = makeVerbose(Args)
    Cfg,Suppliers = prepareInputs(Args,verbose)

    outputFn = Path(Cfg[fOutputFilename])
    duplicatesFn = Cfg[fDuplicatesFilename]
    allnamesFn = Cfg[fAllNamesFilename]
    encodings = Cfg['encodings']
    Items = {}

    output_encoding = None
    for supplier_name, supplier_def in Suppliers.items():
        itms,encoding = loadItems(supplier_def, encodings, verbose)
        if itms is not None:
            Items[supplier_name]=itms
            if encoding is not None:
                if output_encoding is None:
                    output_encoding = encoding
                else:
                    verbose(f'colliding encodings : {output_encoding} and {encoding}, switching to utf-8')
                    output_encoding = 'utf-8'
    
    SelectedItems,Duplicates = selectItems(Items, verbose)
    verbose(f'using {output_encoding} as output encoding')
    writeResult(SelectedItems,outputFn, output_encoding)
    writeDuplicates(Duplicates, duplicatesFn, output_encoding)
    writeNames(Items, allnamesFn, output_encoding)

    if Args.search is not None:
        sit = Args.search.lower()
        for sn,vals in Items.items():
            if sit in vals:
                print( f'item {Args.search} in {sn}')
        if sit in SelectedItems:
            print( f'item {Args.search} in selected items')


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
    parser.add_argument("-search",type=str,help="search item in the final results")
    Args = parser.parse_args()

    if Args.test:
        unittest.main(argv=['program_selectory.py'])
    else:
        main(Args)
