from __future__ import division, print_function, unicode_literals, absolute_import
import warnings
warnings.simplefilter('default',DeprecationWarning)
if not 'xrange' in dir(__builtins__):
  xrange = range

import xml.etree.ElementTree as ET
import xml.dom.minidom as pxml
import os
import sys
import copy
import numpy as np

class YakMultigroupLibraryParser():
  """
    import the user-edited input file, build list of strings with replaceable parts
  """
  #Functions Used for Reading Yak Multigroup Cross Section Library (Also including some functions for checking and recalculations)
  def __init__(self,inputFiles):
    """
      Accept the input file and store XS data
      @ In, inputFiles, list(str), string list of input filenames that might need parsing.
      @ Out, None.
    """
    self.inputFiles     = inputFiles
    self.tabs           = {} #dict of tab points, keyed on tabNames
    self.reactionTypes  = [] #list of reaction types to be included
    self.tableReacts    = [] #list of tablewise reactions
    self.libs           = {} #dictionaries for libraries of tabulated xs values
    self.xmlsDict       = {} #connects libraries name and tree objects: {libraryName:objectTree}
    self.filesDict      = {} #connects names of files  and libraries name: {librariesName:fileName}
    self.matLibMaps     = {} #connects material id and libraries name: {matID:librariesName}
    self.matTreeMaps    = {} #connects material id and xml objects: {matID:objectTree}
    self.defaultNu      = 2.43 #number of neutrons per fission
    self.defaultKappa   = 195*1.6*10**(-13) #Energy release per fission
    self.aliases        = {} #alias to XML node dict
    self.validReactions = ['Total','Fission','Removal','Transport','Scattering','nuFission','kappaFission',
                           'FissionSpectrum','DNFraction','DNSpectrum','NeutronVelocity','DNPlambda'] #These are all valid reactions for Yak XS format
    self.perturbableReactions = ['Fission','Capture','TotalScattering','Nu','Kappa'] #These are all valid perturbable reactions for RAVEN
    self.level0Element  = 'Multigroup_Cross_Section_Libraries' #root element tag is always the same for Yak XS format
    self.level1Element  = 'Multigroup_Cross_Section_Library'   #level 1 element tag is always Multigroup_Cross_Section_Library
    self.level2Element  = ['Tabulation','AllReactions','TablewiseReactions','LibrarywiseReactions'] #These are some of the level 2 element tag with string vector xmlnode.text, without xml subnodes
    self.toBeReadXML    = [] #list of XML nodes that need to be read.
    self.libsKeys       = {} #dict to store library keys: {mglib_ID:{gridIndex:{IsotopeName:[reactions]}}}

    #read in cross-section files, unperturbed files
    for xmlFile in inputFiles:
      if not os.path.exists(xmlFile): raise IOError('The following Yak multigroup cross section library file: ' + xmlFile + ' is not found')
      tree = ET.parse(xmlFile)
      root = tree.getroot()
      if root.tag == self.level0Element:
        self.xmlsDict[root.attrib['Name']] = tree
        #self.filesDict[root.attrib['Name']] = xmlFile
        self.filesDict[xmlFile] = root.attrib['Name']
        self.libs[root.attrib['Name']] = {}
        self.libsKeys[root.attrib['Name']] = {}
        mgDict = self.libs[root.attrib['Name']]
        mgDictKeys =  self.libsKeys[root.attrib['Name']]
        self.nGroup = int(root.attrib['NGroup']) #total number of neutron energy groups
        for mgLib in root:
          self.matLibMaps[mgLib.attrib['ID']] = root.attrib['Name']
          self.matTreeMaps[mgLib.attrib['ID']] = mgLib
          mgDict[mgLib.attrib['ID']] = {}
          mgDictKeys[mgLib.attrib['ID']] = {}
          self._readYakXSInternal(mgLib,mgDict[mgLib.attrib['ID']],mgDictKeys[mgLib.attrib['ID']])
          self._readAdditionalYakXS(mgLib,mgDict[mgLib.attrib['ID']])
          self._checkYakXS(mgDict[mgLib.attrib['ID']],mgDictKeys[mgLib.attrib['ID']])
      else:
        msg = 'In YakMultigroupLibraryParser, root element of XS file is always ' + self.rootElement + ';\n'
        msg = msg + 'while the given XS file has different root element: ' + root.tag + "!"
        raise IOError(msg)
    print('+++++++++Library Keys++++++++++++')
    print(str(self.libsKeys))

  def initialize(self,aliasTree):
    """
      Initialize aliases
      @ In, aliasTree, xml.etree.ElementTree.ElementTree, alias tree
      @ Out, None
    """
    perturbable = ['Fission','Capture','Scattering','Nu','Kappa']
    root = aliasTree.getroot()
    self.aliases={}
    if root.tag != self.level0Element:
      raise IOError('Invalid root tag: ' + root.tag +' is provided.' + ' The valid root tag should be: ' + self.level0Element)
    self.aliases[root.attrib['Name']] ={}
    self.aliasesNGroup = int(root.attrib['NGroup'])
    self.aliasesType = root.attrib['Type']
    subAlias = self.aliases[root.attrib['Name']]
    for child in root:
      if child.tag != self.level1Element:
        raise IOError('Invalid subnode tag: ' + child.tag +' is provided.' + ' The valid subnode tag should be: ' + self.level1Element)
      subAlias[child.attrib['ID']] = {}
      #read the cross section alias for each library (or material)
      self._readXSAlias(child,subAlias[child.attrib['ID']])

    print('+++++++++Aliases Lib++++++++++++')
    print(self.aliases)

  def _readXSAlias(self,xmlNode,aliasXS):
    """
      Read the cross section alias for each library
      @ In, xmlNode, xml.etree.ElementTree.Element, xml element
      @ In, aliasXS, dict, dictionary used to store the cross section aliases
      @ Out, None
    """
    for child in xmlNode:
      if child.tag in self.perturbableReactions:
        grid = self._stringSpacesToTuple(child.attrib['gridIndex'])
        if grid not in aliasXS.keys(): aliasXS[grid] = {}
        mat = child.attrib['mat']
        if mat not in aliasXS[grid].keys(): aliasXS[grid][mat] = {}
        mt = child.tag
        aliasXS[grid][mat][mt] = []
        groupIndex = child.get('gIndex')
        if groupIndex == None:
          varsList = list(var.strip() for var in child.text.strip().split(','))
          if len(varsList) != self.aliasesNGroup:
            msg = str(self.aliasesNGroup) + ' variables should be provided for ' + child.tag + ' of material ' + child.attrib['mat']
            msg = msg + ' in grid ' + child.attrib['gridIndex'] + '! '
            msg = msg + "Only " + len(varsList) + " variables is provided!"
            raise IOError(msg)
          aliasXS[grid][mat][mt] = varsList
        else:
          varsList = [0]*self.aliasesNGroup
          pertList = list(var.strip() for var in child.text.strip().split(','))
          groups = self._stringSpacesToListInt(groupIndex)
          if len(groups) != len(pertList):
            raise IOError('The group indices is not consistent with the perturbed variables list')
          for g in groups:
            varsList[g-1] = pertList[g-1]
          aliasXS[grid][mat][mt] = varsList
      else:
        raise IOError('The reaction ' + child.tag + ' can not be perturbed!')

  def _stringSpacesToTuple(self,text):
    """
      Turns a space-separated text into a tuple
      @ In, text, string, string
      @ Out, members, list(int), list of members
    """
    members = tuple(int(c.strip()) for c in text.strip().split())
    return members

  def _stringSpacesToListInt(self,text):
    """
      Turns a space-separated text into a list of int
      @ In, text, string, string
      @ Out, members, list(int), list of members
    """
    members = list(int(c.strip()) for c in text.strip().split())
    return members

  def _stringSpacesToListFloat(self,text):
    """
      Turns a space-separated text into a list of float
      @ In, text, string, string
      @ Out, members, list(float), list of members
    """
    members = list(float(c.strip()) for c in text.strip().split())
    return members

  def _stringSpacesToNumpyArray(self,text):
    """
      Turns a space-separated text into a list of float
      @ In, text, string, string
      @ Out, members, numpy.array, list of members
    """
    members = np.asarray(list(float(c.strip()) for c in text.strip().split()))
    return members

  def _stringSpacesToListString(self,text):
    """
      Turns a space-separated text into a list of constituent members
      @ In, text, string, string
      @ Out, members, list(string), list of members
    """
    members = list(c.strip() for c in text.strip().split())
    return members

  def _readYakXSInternal(self,library,pDict,keyDict):
    """
      Load the Yak multigroup library
      @ In, library, xml.etree.ElementTree.Element, element
      @ In, pDict, dict, dictionary to store the multigroup library
      @ In, keyDict, dict, dictionary to store the multigroup library node names, use to trace the cross section types for given isotope at given gridIndex
      @ Out, None
    """
    #read data for this library
    for subNode in library:
      # read tabulates
      self._readNextLevel(subNode,pDict,keyDict)

  def _parentAction(self,parentNode,libDict,keyDict):
    """
      Default action for parent nodes with children
      @ In, parentNode, xml.etree.ElementTree.Element, element
      @ In, libDict, dict, dictionary of multigroup library
      @ In, keyDict, dict, dictionary to store the multigroup library node names, use to trace the cross section types for given isotope at given gridIndex
      @ Out, None
    """
    for child in parentNode:
      self._readNextLevel(child,libDict,keyDict)

  def _readNextLevel(self,xmlNode,pDict,keyDict):
    """
      Uses xmlNode tag to determine next reading algorithm to perform.
      @ In, xmlNode, xml.etree.ElementTree.Element, element
      @ In, pDict, dict, dictionary for child's parent
      @ In, keyDict, dict, dictionary to store the multigroup library node names, use to trace the cross section types for given isotope at given gridIndex
      @ Out, None
    """
    # case: child.tag
    if xmlNode.tag in self.level2Element:
      pDict[xmlNode.tag] = self._stringSpacesToListString(xmlNode.text)
    elif xmlNode.tag == 'ReferenceGridIndex':
      pDict[xmlNode.tag] = self._stringSpacesToListInt(xmlNode.text)
    elif xmlNode.tag == 'Table':
      dictKey = self._stringSpacesToTuple(xmlNode.attrib['gridIndex'])
      pDict[dictKey] = {}
      keyDict[dictKey] = {}
      self._parentAction(xmlNode,pDict[dictKey],keyDict[dictKey])
    elif xmlNode.tag == 'Tablewise':
      pDict[xmlNode.tag] = {}
      self._readTablewise(xmlNode,pDict[xmlNode.tag])
    elif xmlNode.tag == 'Isotope':
      #check if the subnode includes the XS
      pDict[xmlNode.attrib['Name']] = {}
      keyDict[xmlNode.attrib['Name']] = []
      hasSubNode = False
      for child in xmlNode:
        if child != None:
          hasSubNode = True
          break
      if hasSubNode:
        self._readIsotopXS(xmlNode,pDict[xmlNode.attrib['Name']],keyDict[xmlNode.attrib['Name']])
    #store the xmlNode tags that have not been parsed
    else:
      self.toBeReadXML.append(xmlNode.tag)

  def _readIsotopeXS(self,node,pDict,keyList):
    """
      Reads in Tablewise entry for rattlesnake and stores values
      @ In, node, xml.etree.ElementTree.Element, node
      @ In, pDict, dict, xml dictionary
      @ In, keyList, list, dictionary to store the multigroup library node names, use to trace the cross section types for given isotope at given gridIndex
      @ Out, None
    """
    #the xs structure is same as Tablewise xs data
    self._readTablewise(node,pDict,keyList)

  def _readLibrarywise(self,node,pDict):
    """
      Reads in Librarywise entry for rattlesnake and stores values
      @ In, node, xml.etree.ElementTree.Element, node
      @ In, pDict, dict, xml dictionary
      @ Out, None
    """
    #the xs structure is same as Tablewise xs data
    self._readTablewise(node,pDict)

  def _readTablewise(self,node,pDict,keyList=None):
    """
      Reads in Tablewise entry for rattlesnake and stores values
      @ In, node, xml.etree.ElementTree.Element, node
      @ In, pDict, dict, xml dictionary
      @ In, keyList, list, list to store the multigroup library node names, use to trace the cross section types for given isotope at given gridIndex
      @ Out, None
    """
    orderScattering = int(node.attrib['L'])
    for child in node:
      #FIXME the validReactions is documented in Yak, but it seems this is not sure. Other cross sections can also be included, such as Capture, Nalpha, ...
      #if child.tag not in self.validReactions:
      #  raise IOError("The following reaction type " + child.tag + " is not valid!")
      if keyList != None:
        keyList.append(child.tag)
      #read all xs for all reaction types except Scattering
      if child.tag != 'Scattering':
        pDict[child.tag]= self._stringSpacesToNumpyArray(child.text)
      #read xs sections for Scattering
      else:
        #TODO scattering is hard to read in.
        self._readScatteringXS(child,pDict,orderScattering)

      print('+++++++++' + child.tag + '++++++++++++')
      print(pDict[child.tag])

  def _readScatteringXS(self,node,pDict,orderScattering):
    """
      Reads the Scattering block for Yak multigroup cross section library
      @ In, node, xml.etree.ElementTree.Element, xml node
      @ In, pDict, dict, xml dictionary
      @ In, orderScattering, int, order of spherical harmonics expansioin for scattering
      @ Out, None
   """
    has_profile = False
    pDict['ScatteringOrder'] = orderScattering
    if int(node.get('profile')) == 1: has_profile = True
    if has_profile:
      for child in node:
        if child.tag == 'Profile':
          profileValue = self._stringSpacesToListInt(child.text)
          pDict['ScatterStart'] = profileValue[0::2]
          pDict['ScatterEnd'] = profileValue[1::2]
        elif child.tag == 'Value':
          scatteringValue = self._stringSpacesToNumpyArray(child.text) #store in 1-D array
      pDict['Scattering'] = np.zeros((self.nGroup*(orderScattering+1),self.nGroup))
      ip = 0
      for l in range(orderScattering+1):
        for g in range(self.nGroup):
          for gr in range(pDict['ScatterStart'][g+l*self.nGroup]-1,pDict['ScatterEnd'][g+l*self.nGroup]):
            pDict['Scattering'][g+l*self.nGroup][gr] = scatteringValue[ip]
            ip += 1
    else:
      scatteringValue = self._stringSpacesToNumpyArray(child.text) #store in 1-D array
      pDict[child.tag] = scatteringValue.reshape((self.nGroup*(orderScattering+1),self.nGroup))
    #calculate Total Scattering
    totScattering = np.zeros(self.nGroup)
    for g in range(self.nGroup):
      totScattering[g] = np.sum(pDict['Scattering'][g])
    pDict['TotalScattering'] = totScattering

  def _readAdditionalYakXS(self,xmlNode,pDict):
    """
      Read addition cross sections that have not been read via method self._readYakXSInternal,
      such as Tabulation Grid, Librarywise.
      @ In, pDict, dict, dictionary stores all the cross section data for given multigroup library (or material)
      @ Out, None
    """
    for child in xmlNode:
      #read the tabulation grid
      if child.tag in pDict['Tabulation']:
        pDict[child.tag] = self._stringSpacesToNumpyArray(child.text)
        self.toBeReadXML.remove(child.tag)
      #read the Librarywise cross section data
      elif child.tag == 'Librarywise':
        pDict[child.tag] = {}
        self._readLibrarywise(child,pDict[child.tag])
        self.toBeReadXML.remove(child.tag)
    if len(self.toBeReadXML) != 0:
      raise IOError('The following nodes xml' + str(self.toBeReadXML) + ' have not been read yet!')

  def _checkYakXS(self,pDict,keyDict):
    """
      Recalculate some undefined xs, such as 'Nu', 'Fission', 'Capture'.
      @ In, pDict, dict, dictionary stores all the cross section data for given multigroup library (or material)
      @ In, keyDict, dict, dictionary to store the multigroup library node names, use to trace the cross section types for given isotope at given gridIndex
      @ Out, None
    """
    #make sure pDict include the cross sections, if not, copy from Tablewise data
    for gridKey,isotopeDict in keyDict.items():
      for isotopeKey,reactionList in isotopeDict.items():
        if len(reactionList) == 0:
          pDict[gridKey][isotopeKey] = copy.deepcopy(pDict[gridKey]['Tablewise'])
        #calculate some independent cross sections if they are not in pDict
        #these cross sections can be: fission, total scattering, capture, nu, kappa
        self._recalculateYakXS(pDict[gridKey][isotopeKey])

  def _recalculateYakXS(self,reactionDict):
    """
      Recalculate some undefined xs, such as 'Nu', 'Fission', 'Capture'.
      @ In, reactionDict, dict, dictionary stores all the cross section data for given multigroup library (or material) at given gridIndex and given Isotope
      @ Out, None
    """
    ### fission, nu, kappa
    reactionList = reactionDict.keys()
    if 'nuFission' in reactionList:
      if 'Fission' not in reactionList:
        #recalculate Fission using default Nu
        reactionDict['Fission'] = reactionDict['nuFission']/self.defaultNu
        reactionDict['Nu'] = np.ones(self.nGroup)*self.defaultNu
      else:
        nu = []
        for i in range(self.nGroup):
          if reactionDict['Fission'][i] != 0:
            nu.append(reactionDict['nuFission'][i]/reactionDict['Fission'][i])
          else:
            nu.append(self.defaultNu)
        reactionDict['Nu'] = np.asarray(nu)
      if 'kappaFission' not in reactionList:
        #recalculate kappaFission using default kappa
        reactionDict['kappaFission'] = self.defaultKappa * reactionDict['Fission']
        reactionDict['Kappa'] = np.ones(self.nGroup) * self.defaultKappa
      else:
        kappa = []
        for i in range(self.nGroup):
          if reactionDict['Fission'][i] != 0:
            kappa.append(reactionDict['kappaFission'][i]/reactionDict['Fission'][i])
          else:
            kappa.append(self.defaultKappa)
        reactionDict['Kappa'] = np.asarray(kappa)
    # calculate absoption
    hasTotal = False
    if 'Absorption' not in  reactionList:
      if 'Total' in reactionList:
        reactionDict['Absorption'] = reactionDict['Total'] - reactionDict['TotalScattering']
      else:
        raise IOError('Total cross section is required for this interface, but not provide!')
    else:
      #recalculate capture cross sections
      if 'Capture' not in reactionList:
        if 'nuFission' in reactionList:
          reactionDict['Capture'] = reactionDict['Absorption'] - reactionDict['Fission']
        else:
          reactionDict['Capture'] = reactionDict['Absorption']
    #we may also need to consider to recalculate Removal and DiffusionCoefficient XS.
    #we will implement in the future.

  #Functions used to perturb the yak multigroup cross section libraries
  ##################################################
  #              MODIFYING METHODS                 #
  ##################################################

  def perturb(self,**Kwargs):
    """
      Perturb the input cross sections
      @ In, **Kwargs, dict, dictionary containing raven sampled var value
      @ Out, None
    """
    self.pertLib = copy.deepcopy(self.libs)
    self.modDict = Kwargs['SampledVars']
    pertFactor = copy.deepcopy(self.aliases)
    #generate the pertLib
    self._computePerturbations(pertFactor,self.pertLib)
    print(pertFactor)
    for libsKey, libDict in pertFactor.items():
      for libID, gridDict in libDict.items():
        self._rebalanceXS(self.pertLib[libsKey][libID],gridDict,pertFactor[libsKey][libID])

  def _nextLevelPerturbation(self,factorDict,pertDict):
    """
      Default action for parent nodes with children
      @ In, factorDict, dict, dictionary of multigroup library
      @ In, pertDict, dict, dictionary to store the multigroup library node names, use to trace the cross section types for given isotope at given gridIndex
      @ Out, None
    """
    for key, valueDict in factorDict.items():
      self._computePerturbations(valueDict,pertDict[key])

  def _computePerturbations(self,factors,lib):
    """
      compute the perturbed values for input variables
      @ In, factors, dict, dictionary contains all input variables that will be perturbed
      @ In, lib, dict, dictionary contains all the values of input variables
      @ Out, None
    """
    for libKey, libValue in factors.items():
      if type(libValue) == dict:
        self._nextLevelPerturbation(libValue,lib[libKey])
      elif type(libValue) == list:
        groupValues = np.asarray(list(self.modDict[var] for var in libValue))
        factors[libKey] = groupValues
        if self.aliasesType == 'rel':
          lib[libKey] *= groupValues
        elif self.aliasesType == 'abs':
          lib[libKey] += groupValues

        print('+++++++++' + libKey  + '++++++++++++')
        print(lib[libKey])

  def _rebalanceXS(self,libDict,libKeyDict,factorDict):
    """
      Using the perturbed cross sections to recalculate other dependent cross sections
      @ In, libDict, dict, dictionary used to store the cross section data
      @ In, libKeyDict, dict, dictionary used to store the cross section types
      @ In, factorDict, dict, dictionary used to store the perturbation factors
      @ Out, None
    """
    for gridKey,isotopeDict in libKeyDict.items():
      for isotopeKey,reactionList in isotopeDict.items():
        #calculate some independent cross sections if they are not in pDict
        #these cross sections can be: fission, total scattering, capture, nu, kappa
        print(gridKey)
        self._rebalanceYakXS(libDict[gridKey][isotopeKey],factorDict[gridKey][isotopeKey])

  def _rebalanceYakXS(self,reactionDict,perturbDict):
    """
      Recalculate some depedent xs, such as 'Total', 'Absorption', 'Scattering', 'nuFission', 'kappaFission',
      (maybe Removal, Transport).
      @ In, reactionDict, dict, dictionary stores all the cross section data for given multigroup library (or material) at given gridIndex and given Isotope
      @ In, perturbDict, dict, dictionary used to store the perturbation factors
      @ Out, None
    """
    ### fission, nu, kappa, capture, total scattering are assumed to be independent cross section types
    reactionList = perturbDict.keys()
    hasTotalScattering = False
    if 'TotalScattering' in reactionList: hasTotalScattering = True
    if 'Fission' in reactionDict.keys():
      reactionDict['nuFission'] = reactionDict['Fission']*reactionDict['Nu']
      reactionDict['kappaFission'] = reactionDict['Fission']*reactionDict['Kappa']
      reactionDict['Absorption'] = reactionDict['Fission'] + reactionDict['Capture']
      reactionDict['Total'] = reactionDict['Absorption'] + reactionDict['TotalScattering']
    else:
      reactionDict['Absorption'] = reactionDict['Capture']
      reactionDict['Total'] = reactionDict['Absorption'] + reactionDict['TotalScattering']
    #calculate Scattering Cross Sections
    if hasTotalScattering:
      for g in range(self.nGroup):
        if self.aliasesType == 'rel':
          reactionDict['Scattering'][g] *= perturbDict['TotalScattering'][g]
        elif self.aliasesType == 'abs':
          factor = perturbDict['TotalScattering'][g]/self.nGroup
          reactionDict['Scattering'][g] += factor
    #calculate Removal cross sections
    reactionDict['Removal'] = np.asarray(list(reactionDict['Total'][g] - reactionDict['Scattering'][g][g] for g in range(self.nGroup)))

    print('+++++++++New Fission++++++++++++')
    print(reactionDict['Fission'])
    print('+++++++++New Nu++++++++++++')
    print(reactionDict['Nu'])
    print('+++++++++New Kappa++++++++++++')
    print(reactionDict['Kappa'])
    print('+++++++++New Capture++++++++++++')
    print(reactionDict['Capture'])

    print('+++++++++New NuFission++++++++++++')
    print(reactionDict['nuFission'])
    print('+++++++++New kappaFission++++++++++++')
    print(reactionDict['kappaFission'])
    print('+++++++++New Absorption++++++++++++')
    print(reactionDict['Absorption'])
    print('+++++++++New Total++++++++++++')
    print(reactionDict['Total'])
    print('+++++++++New Removal++++++++++++')
    print(reactionDict['Removal'])
    print('+++++++++New Scattering++++++++++++')
    print(reactionDict['Scattering'])

  def _addSubElementForIsotope(self,xmlNode):
    """
      Check if there is a subelement under node Isotope, if not, add the one from the Tablewise (in the future, if Tablewise is not available, add it from Librarywise)
      @ In, xmlNode, xml.etree.ElementTree.Element, xml node
      @ Out, None
    """
    tableWise = xmlNode.find('Tablewise')
    if tableWise is not None:
      for child in tableWise:
        for isotope in xmlNode.findall('Isotope'):
          if isotope.find(child.tag) is not None: break
          isotope.append(copy.deepcopy(child))

  def _replaceXMLNodeText(self,xmlNode,reactionDict):
    """
      @ In, xmlNode, xml.etree.ElementTree.Element, xml node
      @ In, reactionDict, dict, dictionary contains the cross sections and their values
      @ Out, None
    """
    for child in xmlNode:
      if child.tag in reactionDict.keys() and child.tag != 'Scattering':
        child.text = '  '.join(['%.5e' % num for num in reactionDict[child.tag]])
      elif child.tag in reactionDict.keys() and child.tag == 'Scattering':
        for childChild in child:
          #if childChild.tag == 'Profile': child.remove(childChild)
          if childChild.tag == 'Value':
            msg = ''
            for g in range(reactionDict[child.tag].shape[0]):
              msg = msg + '\n' + '            '+' '.join(['%.5e' % num for num in reactionDict[child.tag][g][reactionDict['ScatterStart'][g]-1:reactionDict['ScatterEnd'][g]]])
            childChild.text = msg + '\n'

  def _prettify(self,tree):
    """
      Script for turning XML tree into something mostly RAVEN-preferred.  Does not align attributes as some devs like (yet).
      The output can be written directly to a file, as file('whatever.who','w').writelines(prettify(mytree))
      @ In, tree, xml.etree.ElementTree object, the tree form of an input file
      @Out, towrite, string, the entire contents of the desired file to write, including newlines
    """
    #make the first pass at pretty.  This will insert way too many newlines, because of how we maintain XML format.
    pretty = pxml.parseString(ET.tostring(tree.getroot())).toprettyxml(indent='  ')
    #loop over each "line" and toss empty ones, but for ending main nodes, insert a newline after.
    towrite=''
    for line in pretty.split('\n'):
      if line.strip()=='':continue
      towrite += line.rstrip()+'\n'
    return towrite

  def writeNewInput(self,**Kwargs,inFiles=None):
    """
      Generates a new input file with the existing parsed dictionary.
      @ In, **Kwargs, dict, dictionary containing raven sampled var value
      @ In, inFiles, Files list of new input files to return
      @ Out, None.
    """
    outFiles = {}
    if inFiles == None:
      outFiles = self.filesDict
      for outFile in outFiles:
        outFile.setBase('perturb'+'~'+outFile.getBase())
    else:
      for inFile in inFiles:
        if inFile in self.filesDict.keys():
          libsKey = self.filesDict[inFile]
          if type(Kwargs['prefix']) in [str,type("")]:
            inFile.setBase(Kwargs['prefix']+'~'+inFile.getBase())
          else:
            inFile.setBase(str(Kwargs['prefix'][1][0])+'~'+inFile.getBase())
          outFiles[inFile.getAbsFile()] = libsKey

    for fileName,libsKey in outFiles.items():
      newFile = open(fileName,'w')
      tree = self.xmlsDict[libsKey]
      if libsKey not in self.aliases.keys(): break
      root = tree.getroot()
      for child in root:
        libID = child.attrib['ID']
        if libID not in self.aliases[libsKey].keys(): break
        for childChild in child:
          if childChild.tag == 'Table':
            gridIndex = self._stringSpacesToTuple(childChild.attrib['gridIndex'])
            if gridIndex not in self.aliases[libsKey][libID].keys(): break
            self._addSubElementForIsotope(childChild)
            for childChildChild in childChild:
              if childChildChild.tag == 'Isotope':
                mat = childChildChild.attrib['Name']
                if mat not in self.aliases[libsKey][libID][gridIndex].keys(): break
                self._replaceXMLNodeText(childChildChild,self.pertLib[libsKey][libID][gridIndex][mat])
      toWrite = self._prettify(tree)
      newFile.writelines(toWrite)
      newFile.close()

