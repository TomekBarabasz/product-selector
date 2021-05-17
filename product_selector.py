import sys,argparse,re,unittest
from pathlib import Path
from collections import namedtuple
from datetime import datetime
from common import *


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
    Items,output_encoding = LoadItems(Suppliers, encodings, verbose)
    
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
